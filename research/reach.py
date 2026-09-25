"""Reading the open web, for the sources an API does not cover.

The registry in `sources.py` reaches APIs that hand back structured records. Plenty of what a
research agent needs is not behind an API at all: a court's press page, a regulator's news list,
a working paper posted as a PDF, a university notice. This module reads those — and only those.

The idea is borrowed from Agent Reach (MIT, github.com/Panniantong/Agent-Reach), which equips an
agent with internet access across many platforms. Half of that project is deliberately not here.
It also reaches Twitter, Instagram, LinkedIn and Xiaohongshu through a logged-in session, and its
own documentation suggests throwaway accounts "to avoid platform detection". That is scraping
against a platform's terms with evasion as the method, and it is not something this repository is
going to do under Matej's name. What is taken is the free, public, no-credential half: a page, a
feed, a transcript a publisher already offers, a repository the official API will hand over.

The rules this module keeps, none of which are optional:

- **robots.txt decides.** Every host is asked once per run, and a Disallow is final. There is no
  override flag, because a flag would eventually be used.
- **One request at a time per host**, no closer together than the source's own `rate_s`.
- **A User-Agent that says who this is** and how to complain, so a publisher can block us by name
  rather than by guessing.
- **No cookies, no logins, no credentials.** A page that needs an account is a page this module
  reports as needing an account.
- **Caps on everything**: bytes, redirects, time. A research agent that downloads a 400 MB PDF at
  three in the morning has become a different kind of program.
"""

import gzip
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

AGENT = ("CognitioFlow-Lector/1.0 (private study and research agent; "
         "one reader, no crawling; contact matej@mgms.eu)")
MAX_BYTES = 5 * 1024 * 1024      # a page or a paper, not an archive
MAX_REDIRECTS = 4
TIMEOUT = 30
MIN_GAP_S = 1.0                  # floor between two requests to the same host

_robots: dict = {}               # host -> RobotFileParser or None when it could not be read
_last_hit: dict = {}             # host -> monotonic time of the last request


class Refused(Exception):
    """The fetch did not happen, and why. Never raised for a network hiccup — only for a rule."""


def host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def _opener():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            new = super().redirect_request(req, fp, code, msg, headers, newurl)
            if new is not None:
                new.redirect_count = getattr(req, "redirect_count", 0) + 1
                if new.redirect_count > MAX_REDIRECTS:
                    raise Refused("too many redirects")
            return new
    return urllib.request.build_opener(NoRedirect)


def robots_allows(url: str, agent: str = AGENT, opener=None) -> bool:
    """Ask the host's robots.txt once per run. A host that cannot be asked is treated as allowing:
    an unreachable robots.txt is the publisher's outage, not a refusal — but a reachable one that
    says no is final."""
    host = host_of(url)
    if host not in _robots:
        parser = urllib.robotparser.RobotFileParser()
        robots_url = urllib.parse.urlunsplit((urllib.parse.urlsplit(url).scheme or "https", host, "/robots.txt", "", ""))
        try:
            request = urllib.request.Request(robots_url, headers={"User-Agent": agent})
            with (opener or _opener()).open(request, timeout=10) as reply:
                parser.parse(reply.read(200_000).decode("utf-8", "replace").splitlines())
            _robots[host] = parser
        except Exception:
            _robots[host] = None
    parser = _robots[host]
    return True if parser is None else parser.can_fetch(agent, url)


def _wait(host: str, rate_s: float, clock=time.monotonic, sleep=time.sleep):
    gap = max(rate_s, MIN_GAP_S)
    last = _last_hit.get(host)
    if last is not None:
        remaining = gap - (clock() - last)
        if remaining > 0:
            sleep(remaining)
    _last_hit[host] = clock()


def fetch(url: str, rate_s: float = MIN_GAP_S, opener=None, clock=time.monotonic, sleep=time.sleep) -> dict:
    """One polite GET of a public page. Returns {url, status, content_type, body, bytes}.
    Raises Refused when a rule says no — robots, scheme, size, or a page that wants an account."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise Refused(f"only http(s) is read, not {parts.scheme or 'a bare path'}")
    if not robots_allows(url, opener=opener):
        raise Refused(f"robots.txt at {host_of(url)} disallows this path")
    _wait(host_of(url), rate_s, clock=clock, sleep=sleep)

    request = urllib.request.Request(url, headers={
        "User-Agent": AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.5",
        "Accept-Encoding": "gzip",
    })
    try:
        with (opener or _opener()).open(request, timeout=TIMEOUT) as reply:
            raw = reply.read(MAX_BYTES + 1)
            status = getattr(reply, "status", 200)
            ctype = reply.headers.get("Content-Type", "")
            if reply.headers.get("Content-Encoding", "") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise Refused(f"{host_of(url)} wants an account or blocks this reader ({e.code}) — not worked around")
        raise
    if len(raw) > MAX_BYTES:
        raise Refused(f"over {MAX_BYTES // 1024 // 1024} MB — left where it is")
    return {"url": url, "status": status, "content_type": ctype, "body": raw, "bytes": len(raw)}


_SCRIPT = re.compile(rb"(?is)<(script|style|noscript|template)\b.*?</\1>")
_TAG = re.compile(rb"(?s)<[^>]+>")
_TITLE = re.compile(rb"(?is)<title[^>]*>(.*?)</title>")
_ENTITY = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&rsquo;": "’"}


def readable(page: dict, limit: int = 40000) -> dict:
    """The words on the page, without the furniture. Deliberately simple: a real extractor is a
    dependency and a maintenance burden, and what a research agent needs is the prose and the title."""
    body = page.get("body") or b""
    ctype = (page.get("content_type") or "").lower()
    if "pdf" in ctype or body[:4] == b"%PDF":
        return {"title": "", "text": "", "note": "PDF — hand it to the extractor the app already has", "url": page.get("url", "")}
    title_match = _TITLE.search(body)
    stripped = _TAG.sub(b" ", _SCRIPT.sub(b" ", body))
    text = stripped.decode("utf-8", "replace")
    for entity, char in _ENTITY.items():
        text = text.replace(entity, char)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    title = ""
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1).decode("utf-8", "replace")).strip()
        for entity, char in _ENTITY.items():
            title = title.replace(entity, char)
    return {"title": title, "text": text[:limit], "note": "", "url": page.get("url", "")}


def read(url: str, rate_s: float = MIN_GAP_S, **kw) -> dict:
    """fetch + readable, the one call the agent actually wants. A refusal comes back as a record
    with a reason rather than an exception, because one unreachable page must not end a run."""
    try:
        page = fetch(url, rate_s=rate_s, **kw)
    except Refused as why:
        return {"url": url, "title": "", "text": "", "note": f"not read: {why}", "ok": False}
    except Exception as e:
        return {"url": url, "title": "", "text": "", "note": f"not read: {type(e).__name__}", "ok": False}
    out = readable(page)
    out["ok"] = not out["note"]
    out["bytes"] = page["bytes"]
    return out
