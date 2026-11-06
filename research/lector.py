#!/usr/bin/env python3
"""Lector — the reading agent. Scriptorium copies, Claude decides, Lector reads.

A routine, not a chat. It wakes on a schedule, polls the open academic and public-record APIs
in `sources.py`, normalises what comes back, scores it for evidence quality as well as
relevance, and writes two artefacts the CommandTerminal can display:

    ~/.cognitio/lector/feed.json      every record kept, newest run first
    ~/.cognitio/lector/digest.txt     an 80-column ANSI panel, ready to paste into a lane

It costs nothing per run. No model is called: this stage is retrieval, de-duplication and
ranking, all of which are cheaper and more reliable as plain code than as tokens. When a
record earns a real read, that is when a Claude agent gets spawned — see
`.claude/agents/lector.md`. The expensive judgement stays rare and deliberate, which is the
same rule the fleet already runs on.

Constraints kept on purpose, to match the rest of the fleet:

- **Stdlib only.** No requests, no rich, no textual. It installs on the Mac with nothing.
- **80x24.** The digest degrades by hiding detail, never by breaking the frame.
- **Colour is never the only signal.** Every flag has a glyph as well as a colour.
- **Nothing private leaves the machine.** Every source here is public by construction; no
  course material, note text or `data/` content is ever sent anywhere. Lector reads the
  outside world in, never the inside world out.

Usage:
    python3 lector.py --list                 what is registered, and why
    python3 lector.py --check                probe every endpoint, report what answers
    python3 lector.py --once                 one harvest across all tracks
    python3 lector.py --once --track quant   one track only
    python3 lector.py --render               redraw the digest from the stored feed
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import adapters  # noqa: E402
import scoring  # noqa: E402
import sources  # noqa: E402

HOME = pathlib.Path(os.environ.get("LECTOR_HOME", "~/.cognitio/lector")).expanduser()
FEED = HOME / "feed.json"
DIGEST = HOME / "digest.txt"
STATE = HOME / "state.json"
LOG = HOME / "lector.log"

# A real contact address is what every one of these APIs asks for in return for free access.
CONTACT = os.environ.get("LECTOR_CONTACT", "matej@mgms.eu")
AGENT = f"CognitioFlow-Lector/1.0 (+https://app.cognitioflow.ai; mailto:{CONTACT})"

KEEP_RUNS = 12        # how many harvests stay in the feed before the oldest is dropped
KEEP_SEEN = 5000      # uids remembered, so a record is new exactly once

# Flags get a glyph as well as a colour, because colour is never the only signal.
GLYPH = {
    "REPLICATION": ("✓", "\033[32m"),   # green: checks someone's homework
    "RETRACTED": ("!", "\033[31m"),     # red: must be seen because it is wrong
    "NO-OOS": ("~", "\033[33m"),        # yellow: performance claim, no holdout
    "MULTI-TEST": ("~", "\033[33m"),
    "PREPRINT": ("·", "\033[90m"),
    "CROSSOVER": ("+", "\033[36m"),     # cyan: serves both tracks
    "COURSE": ("*", "\033[35m"),        # magenta: exam material too
    "NEW": ("›", "\033[97m"),
}
RESET = "\033[0m"
DIM = "\033[90m"


# ----------------------------------------------------------------------------- state

def _load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    tmp.replace(path)          # atomic: the terminal never reads a half-written feed


def _log(line: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    with LOG.open("a") as fh:
        fh.write(f"{stamp}  {line}\n")


# ----------------------------------------------------------------------------- fetching

def fetch(url: str, timeout: int = 30) -> bytes:
    """One GET, with the User-Agent every one of these APIs asks for."""
    request = urllib.request.Request(url, headers={
        "User-Agent": AGENT,
        "Accept": "application/json, application/atom+xml;q=0.9, */*;q=0.5",
    })
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.read()


def build_url(source, since: str, rows: int, query: str = "") -> str:
    return (source.endpoint
            .replace("{since}", since)
            .replace("{rows}", str(rows))
            .replace("{query}", query))


def harvest_one(source, since: str, rows: int) -> tuple:
    """Poll one source. Returns `(records, error)` — never raises on a network fault.

    A source that is down must not take the run with it. The digest shows the failure and
    the other twenty sources still arrive.
    """
    try:
        url = build_url(source, since, rows)
        payload = fetch(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return [], f"{type(exc).__name__}: {exc}"

    adapter = adapters.ADAPTERS.get(source.extract)
    if adapter is None:
        return [], f"no adapter named {source.extract!r}"
    try:
        return adapter(payload, source), ""
    except Exception as exc:                        # a shape change upstream, not a bug here
        return [], f"parse failed ({type(exc).__name__}: {exc})"


def _identity(record) -> str:
    """What makes two records the same thing, regardless of which API produced them.

    A DOI is authoritative when there is one. Otherwise fall back to the title with everything
    but letters and digits stripped, which catches the same preprint arriving from arXiv and
    from OpenAlex with different punctuation.
    """
    if record.doi:
        return f"doi:{record.doi.lower()}"
    flat = "".join(ch for ch in record.title.lower() if ch.isalnum())
    return f"title:{flat}" if flat else f"uid:{record.uid}"


def dedupe(records) -> tuple:
    """Collapse the same paper arriving from several sources. Returns `(kept, merged_count)`.

    OpenAlex and Crossref both carry the same DOI; arXiv and OpenAlex both carry the same
    preprint. Without this the panel shows one paper three times and buries two others.

    The copy that survives is the one from the most authoritative source, because that is the
    one worth citing. A tie goes to the record carrying an abstract.
    """
    best = {}
    for record in records:
        key = _identity(record)
        held = best.get(key)
        if held is None or (record.authority, not record.abstract) < (held.authority, not held.abstract):
            best[key] = record
    kept = list(best.values())
    return kept, len(records) - len(kept)


def harvest(track: str = "", rows: int = 25, days: int = 14, dry: bool = False) -> dict:
    """One full pass. This is the routine the scheduler calls."""
    today = dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    state = _load(STATE, {"seen": [], "sources": {}})
    seen = set(state.get("seen", []))

    kept, errors, polled = [], {}, 0
    for source in sources.fetchable(track):
        polled += 1
        if dry:
            print(f"  would poll {source.id}: {build_url(source, since, rows)}")
            continue
        records, error = harvest_one(source, since, rows)
        if error:
            errors[source.id] = error
            _log(f"ERROR {source.id}: {error}")
        fresh = [r for r in records if r.uid not in seen]
        kept.extend(fresh)
        seen.update(r.uid for r in fresh)
        state["sources"][source.id] = {
            "last_run": today.isoformat(),
            "returned": len(records),
            "new": len(fresh),
            "error": error,
        }
        time.sleep(source.rate_s)                   # the politeness each API asks for

    if dry:
        return {"dry": True, "sources": polled}

    kept, merged = dedupe(kept)
    ranked = scoring.rank(kept, today)
    run = {
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "track": track or "all",
        "since": since,
        "sources_polled": polled,
        "new_records": len(ranked),
        "duplicates_merged": merged,
        "errors": errors,
        "records": [r.as_dict() for r in ranked],
    }

    feed = _load(FEED, {"runs": []})
    feed["runs"] = ([run] + feed.get("runs", []))[:KEEP_RUNS]
    _save(FEED, feed)

    state["seen"] = list(seen)[-KEEP_SEEN:]
    _save(STATE, state)
    _log(f"run track={run['track']} polled={polled} new={len(ranked)} errors={len(errors)}")

    DIGEST.write_text(render(feed, colour=False))
    return run


# ----------------------------------------------------------------------------- rendering

def render(feed: dict, width: int = 80, height: int = 24, colour: bool = True) -> str:
    """The panel the CommandTerminal shows. Degrades by hiding detail, never by wrapping."""
    runs = feed.get("runs", [])
    if not runs:
        return "LECTOR  no harvest yet — run: python3 research/lector.py --once\n"

    run = runs[0]
    # No side borders, so a content line fills the same width as the rules. Anything narrower
    # and the frame visibly fails to line up.
    body = width
    out = [_rule(width), _line(f" LECTOR · {run['at']} · track {run['track']}", body, colour,
                               bold=True)]

    failed = len(run.get("errors") or {})
    merged = run.get("duplicates_merged") or 0
    summary = (f" {run['new_records']} new from {run['sources_polled']} sources"
               f"{f' · {merged} duplicates merged' if merged else ''}"
               f"{f' · {failed} unreachable' if failed else ''}")
    out.append(_line(summary, body, colour, dim=True))
    out.append(_rule(width))

    # Chrome is 5 lines (rule, header, summary, rule, rule) plus a legend. Each record costs
    # two. Budget in records, not lines, or the panel runs off a 24-row terminal.
    rows = max((height - 6) // 2, 2)
    for record in run.get("records", [])[:rows]:
        marks = "".join(GLYPH.get(f, ("?", ""))[0] for f in record.get("flags", ())[:4])
        title = record.get("title", "")[: body - 22]
        head = f" {record.get('score', 0):4.1f} {marks:<4} {title}"
        out.append(_line(head, body, colour, flags=record.get("flags", ())))
        meta = f"      {record.get('date') or '—'} · {record.get('venue') or record['source_id']}"
        out.append(_line(meta[: body], body, colour, dim=True))

    out.append(_rule(width))
    out.append(_line(_legend(run.get("records", [])), body, colour, dim=True))
    return "\n".join(out) + "\n"


def _legend(records) -> str:
    """Only explain the glyphs actually on screen."""
    present = []
    for record in records:
        for flag in record.get("flags", ()):
            if flag not in present:
                present.append(flag)
    return " " + "  ".join(f"{GLYPH.get(f, ('?', ''))[0]} {f.lower()}" for f in present[:6])


def _rule(width: int) -> str:
    return "─" * width


def _line(text: str, body: int, colour: bool, bold=False, dim=False, flags=()) -> str:
    text = text[:body].ljust(body)
    if not colour:
        return text
    if bold:
        return f"\033[1m{text}{RESET}"
    if dim:
        return f"{DIM}{text}{RESET}"
    for flag in ("RETRACTED", "REPLICATION", "COURSE", "CROSSOVER"):
        if flag in flags:
            return f"{GLYPH[flag][1]}{text}{RESET}"
    return text


# ----------------------------------------------------------------------------- cli modes

def list_registry(track: str = ""):
    """The list, printed. This is the registry as a reading list rather than as code."""
    for name in sources.TRACKS:
        if track and name != track:
            continue
        entries = sources.for_track(name)
        print(f"\n\033[1m{name.upper()}\033[0m  ({len(entries)} sources, "
              f"{len(sources.fetchable(name))} polled automatically)")
        for source in entries:
            state = "poll" if source.fetchable else ("key" if source.needs_key else "manual")
            mark = "?" if source.verify else " "
            print(f"  [{state:>6}]{mark} {source.id:<26} authority {source.authority}  {source.name}")
            for chunk in _wrap(source.why, 84):
                print(f"            {DIM}{chunk}{RESET}")
    print(f"\n{DIM}  ? = endpoint shape not yet verified against the live API "
          f"(run --check on the Mac){RESET}")


def _wrap(text: str, width: int):
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def check():
    """Probe every registered endpoint once and say plainly what answered.

    These endpoints could not be verified from the container this agent was built in — its
    network policy refuses the hosts outright. This mode is how they get verified on the Mac,
    in one pass, before anything is trusted.
    """
    today = dt.date.today()
    since = (today - dt.timedelta(days=7)).isoformat()
    ok = bad = 0
    for source in sources.SOURCES:
        if not source.endpoint:
            print(f"  [ skip ] {source.id:<26} registered, no endpoint (manual source)")
            continue
        if source.needs_key:
            print(f"  [ key  ] {source.id:<26} needs a key — not probed")
            continue
        url = build_url(source, since, 1, query="0000320193")
        try:
            payload = fetch(url, timeout=20)
            adapter = adapters.ADAPTERS.get(source.extract)
            count = len(adapter(payload, source)) if adapter else 0
            print(f"  [  ok  ] {source.id:<26} {len(payload):>7} bytes, {count} records parsed")
            ok += 1
        except Exception as exc:
            print(f"  [ FAIL ] {source.id:<26} {type(exc).__name__}: {exc}")
            bad += 1
        time.sleep(source.rate_s)
    print(f"\n  {ok} reachable, {bad} failed")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lector — the reading agent for Scriptorium.")
    parser.add_argument("--once", action="store_true", help="run one harvest now")
    parser.add_argument("--list", action="store_true", help="print the source registry")
    parser.add_argument("--check", action="store_true", help="probe every endpoint")
    parser.add_argument("--render", action="store_true", help="redraw the digest from the feed")
    parser.add_argument("--track", default="", choices=["", *sources.TRACKS], help="one track only")
    parser.add_argument("--rows", type=int, default=25, help="max records per source")
    parser.add_argument("--days", type=int, default=14, help="how far back to ask")
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--height", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true", help="print the URLs, fetch nothing")
    args = parser.parse_args(argv)

    if args.list:
        list_registry(args.track)
        return 0
    if args.check:
        return check()
    if args.render:
        print(render(_load(FEED, {"runs": []}), args.width, args.height), end="")
        return 0
    if args.once or args.dry_run:
        run = harvest(args.track, args.rows, args.days, dry=args.dry_run)
        if args.dry_run:
            return 0
        print(render(_load(FEED, {"runs": []}), args.width, args.height), end="")
        return 0 if not run.get("errors") else 0   # a dead source is not a failed run

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
