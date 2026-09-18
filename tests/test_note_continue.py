"""Continue: a note that stops part-way can always be finished.

Before this, /continue only worked on notes the app itself had generated and marked with
`<!--cf:continue …-->`. A note pasted in from a chat, imported, or cut off by whatever produced it
got a 400 and stayed half-written for good — which is how the two longest EU notes ended up
stopping mid-sentence. A draft that hits the token cap now also finishes itself before it is stored.
"""
import unittest.mock as mock

from fastapi.testclient import TestClient


def _reply(text: str, stop_reason: str = "end_turn", model: str = "claude-test"):
    m = mock.MagicMock()
    m.content = [mock.MagicMock(type="text", text=text)]
    m.stop_reason = stop_reason
    m.model = model
    return m


def _client_returning(*replies):
    """A fake Anthropic client handing back `replies` in order (the last one repeats)."""
    fake = mock.MagicMock()
    seq = list(replies)
    fake.messages.create.side_effect = lambda *a, **k: seq.pop(0) if len(seq) > 1 else seq[0]
    return fake


def _note(client: TestClient, body: str, title: str = "Half a note") -> str:
    cid = client.get("/api/courses").json()[0]["id"]
    return client.post(f"/api/courses/{cid}/notes", json={"title": title, "body": body}).json()["id"]


# ---------------------------------------------------------------- the marker-free path

def test_continue_finishes_a_note_that_never_had_a_marker(client: TestClient):
    nid = _note(client, "# Week 2\n\n## Core rules\n1. Art 34 TFEU prohibits MEQRs and the")

    import run
    fake = _client_returning(_reply(" lecturer gave Dassonville as the test.\n\n## Gaps / verify\n- nothing"))
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/notes/{nid}/continue")

    assert r.status_code == 200, r.text
    assert r.json()["cut"] is False
    body = client.get(f"/api/notes/{nid}").json()["body"]
    assert "the lecturer gave Dassonville" in body      # joined with no gap and no repetition
    assert body.count("## Core rules") == 1


def test_continue_sends_the_notes_own_text_and_reads_no_course_files(client: TestClient):
    nid = _note(client, "## Case map\n| Case | Rule |\n| Dassonville | all trading rules capable of")

    import run
    fake = _client_returning(_reply(" hindering trade |"))
    with mock.patch.object(run, "client", return_value=fake):
        assert client.post(f"/api/notes/{nid}/continue").status_code == 200

    sent = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "all trading rules capable of" in sent       # the note itself is the context
    assert "=== " not in sent                           # no `=== file name ===` blocks were pulled in


def test_continue_keeps_the_previous_body_as_a_version(client: TestClient):
    nid = _note(client, "stops here and")

    import run
    with mock.patch.object(run, "client", return_value=_client_returning(_reply(" then finishes."))):
        client.post(f"/api/notes/{nid}/continue")

    versions = client.get(f"/api/notes/{nid}/versions").json()
    assert any("stops here and" in (v.get("body") or "") for v in versions) or versions


def test_continue_rejects_an_empty_note(client: TestClient):
    nid = _note(client, "   ")
    r = client.post(f"/api/notes/{nid}/continue")
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_continue_reports_still_cut_when_the_model_hits_the_cap_again(client: TestClient):
    nid = _note(client, "a long note that stops")

    import run
    with mock.patch.object(run, "client", return_value=_client_returning(_reply(" and keeps going", "max_tokens"))):
        r = client.post(f"/api/notes/{nid}/continue")

    assert r.json()["cut"] is True                      # the student can press Continue again
    assert "<!--cf:continue" in client.get(f"/api/notes/{nid}").json()["body"]


# ---------------------------------------------------------------- a draft finishes itself

def test_draft_continues_itself_when_it_stops_at_the_cap(client: TestClient):
    cid = client.get("/api/courses").json()[0]["id"]
    client.post(f"/api/courses/{cid}/files", files={"file": ("w2.txt", b"Art 34 TFEU and Dassonville.", "text/plain")})

    import run
    fake = _client_returning(_reply("# Week 2\n\n## Core rules\n1. Art 34", "max_tokens"),
                             _reply(" TFEU prohibits MEQRs."))
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/notes/draft", json={"week": "", "diagrams": False})

    assert r.status_code == 200, r.text
    body = client.get(f"/api/notes/{r.json()['id']}").json()["body"]
    assert "<!--cf:continue" not in body                # stored finished, not half-written
    assert "Art 34 TFEU prohibits MEQRs." in body
    assert fake.messages.create.call_count == 2


def test_draft_stops_after_the_round_limit(client: TestClient):
    cid = client.get("/api/courses").json()[0]["id"]
    client.post(f"/api/courses/{cid}/files", files={"file": ("w3.txt", b"Art 36 TFEU.", "text/plain")})

    import run
    fake = _client_returning(_reply("never ends", "max_tokens"))
    with mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/notes/draft", json={"week": "", "diagrams": False})

    assert r.status_code == 200
    assert fake.messages.create.call_count == run.DRAFT_ROUNDS   # bounded, never an open loop
    assert "<!--cf:continue" in client.get(f"/api/notes/{r.json()['id']}").json()["body"]
