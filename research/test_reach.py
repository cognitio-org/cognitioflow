"""reach.py against fake HTTP. Nothing here touches the network."""
import io
import time

import pytest

from research import reach


class FakeReply(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Answers robots.txt and pages from a dict of url -> (body, status, headers)."""

    def __init__(self, pages, robots=""):
        self.pages, self.robots, self.asked = pages, robots, []

    def open(self, request, timeout=None):
        url = request.full_url
        self.asked.append(url)
        if url.endswith("/robots.txt"):
            if self.robots is None:
                raise OSError("no robots here")
            return FakeReply(self.robots.encode())
        body, status, headers = self.pages[url]
        if status >= 400:
            import urllib.error
            raise urllib.error.HTTPError(url, status, "no", headers, None)
        return FakeReply(body, status, headers)


@pytest.fixture(autouse=True)
def clean_state():
    reach._robots.clear()
    reach._last_hit.clear()
    yield
    reach._robots.clear()
    reach._last_hit.clear()


def test_a_disallowed_path_is_not_fetched_and_there_is_no_override():
    opener = FakeOpener({}, robots="User-agent: *\nDisallow: /private\n")
    out = reach.read("https://court.example/private/list", opener=opener, sleep=lambda s: None)
    assert out["ok"] is False and "robots.txt" in out["note"]
    assert not any("/private/list" in u for u in opener.asked)      # it never even asked for the page
    assert not hasattr(reach, "IGNORE_ROBOTS") and not hasattr(reach, "FORCE")


def test_an_allowed_page_comes_back_as_words_without_the_furniture():
    html = (b"<html><head><title>Judgment &amp; press release</title><style>p{color:red}</style></head>"
            b"<body><script>tracker()</script><h1>Ruling</h1><p>The appeal is dismissed.</p></body></html>")
    opener = FakeOpener({"https://court.example/news": (html, 200, {"Content-Type": "text/html"})},
                        robots="User-agent: *\nAllow: /\n")
    out = reach.read("https://court.example/news", opener=opener, sleep=lambda s: None)
    assert out["ok"] is True
    assert out["title"] == "Judgment & press release"
    assert "The appeal is dismissed." in out["text"]
    assert "tracker()" not in out["text"] and "color:red" not in out["text"]


def test_a_login_wall_is_reported_not_worked_around():
    opener = FakeOpener({"https://social.example/post/1": (b"", 403, {})}, robots="User-agent: *\nAllow: /\n")
    out = reach.read("https://social.example/post/1", opener=opener, sleep=lambda s: None)
    assert out["ok"] is False
    assert "account" in out["note"] or "blocks" in out["note"]


def test_one_host_is_not_hit_twice_in_a_row_without_waiting():
    slept = []
    now = [100.0]
    opener = FakeOpener({"https://slow.example/a": (b"<p>a</p>", 200, {"Content-Type": "text/html"}),
                         "https://slow.example/b": (b"<p>b</p>", 200, {"Content-Type": "text/html"})},
                        robots="User-agent: *\nAllow: /\n")
    reach.fetch("https://slow.example/a", rate_s=2.0, opener=opener, clock=lambda: now[0], sleep=slept.append)
    reach.fetch("https://slow.example/b", rate_s=2.0, opener=opener, clock=lambda: now[0], sleep=slept.append)
    assert slept and slept[0] == pytest.approx(2.0)      # the second request waited the source's own gap


def test_robots_is_asked_once_per_host_not_once_per_page():
    opener = FakeOpener({f"https://many.example/{n}": (b"<p>x</p>", 200, {"Content-Type": "text/html"}) for n in "abc"},
                        robots="User-agent: *\nAllow: /\n")
    for n in "abc":
        reach.fetch(f"https://many.example/{n}", opener=opener, sleep=lambda s: None)
    assert sum(1 for u in opener.asked if u.endswith("/robots.txt")) == 1


def test_an_unreachable_robots_does_not_block_a_public_page():
    """A publisher's outage is not a refusal. A reachable 'no' is — that is the test above."""
    opener = FakeOpener({"https://gov.example/report": (b"<p>ok</p>", 200, {"Content-Type": "text/html"})}, robots=None)
    out = reach.read("https://gov.example/report", opener=opener, sleep=lambda s: None)
    assert out["ok"] is True


def test_a_pdf_is_handed_on_rather_than_mangled():
    opener = FakeOpener({"https://bank.example/paper.pdf": (b"%PDF-1.7 binary", 200, {"Content-Type": "application/pdf"})},
                        robots="User-agent: *\nAllow: /\n")
    out = reach.read("https://bank.example/paper.pdf", opener=opener, sleep=lambda s: None)
    assert out["text"] == "" and "PDF" in out["note"]


def test_only_http_is_read():
    out = reach.read("file:///etc/passwd", sleep=lambda s: None)
    assert out["ok"] is False and "http" in out["note"]


def test_an_oversized_body_is_left_where_it_is():
    big = b"<p>" + b"x" * (reach.MAX_BYTES + 10) + b"</p>"
    opener = FakeOpener({"https://big.example/dump": (big, 200, {"Content-Type": "text/html"})},
                        robots="User-agent: *\nAllow: /\n")
    out = reach.read("https://big.example/dump", opener=opener, sleep=lambda s: None)
    assert out["ok"] is False and "MB" in out["note"]


def test_the_user_agent_says_who_this_is_and_how_to_complain():
    assert "CognitioFlow" in reach.AGENT and "@" in reach.AGENT
