"""Tests: routes the UI already called but run.py never had (tick-all-in-week, study timer log, case index)."""
import io
from datetime import date


def _cid(client):
    return client.get("/api/courses").json()[0]["id"]


def _selected(client, cid, fid):
    return next(f["selected"] for f in client.get(f"/api/courses/{cid}/files").json() if f["id"] == fid)


def test_toggle_to_sets_explicit_state(client):
    cid = _cid(client)
    fid = client.post(f"/api/courses/{cid}/files", files={"file": ("w1.txt", io.BytesIO(b"Art 34"), "text/plain")}, data={"week": "1"}).json()["id"]
    assert _selected(client, cid, fid) == 1
    for on, want in ((False, 0), (False, 0), (True, 1), (True, 1)):  # idempotent, unlike /toggle
        r = client.post(f"/api/files/{fid}/toggle-to", json={"on": on})
        assert r.status_code == 200 and r.json()["selected"] == want
        assert _selected(client, cid, fid) == want
    assert client.post("/api/files/nope/toggle-to", json={"on": True}).status_code == 404


def test_sessions_log_records_done_time_today(client):
    cid = _cid(client)
    r = client.post(f"/api/courses/{cid}/sessions/log", json={"minutes": 42, "topic": "Drilling European Law"})
    assert r.status_code == 200 and r.json()["minutes"] == 42
    s = next(x for x in client.get("/api/sessions").json() if x["id"] == r.json()["id"])
    assert (s["day"], s["topic"], s["minutes"], s["done"]) == (date.today().isoformat(), "Drilling European Law", 42, 1)
    assert client.get(f"/api/courses/{cid}/stats").json()["study_minutes"] == 42
    assert client.post(f"/api/courses/{cid}/sessions/log", json={"minutes": 0, "topic": ""}).json()["minutes"] == 1


def test_case_index_from_italics_and_case_map_tables(client):
    cid = _cid(client)
    n1 = client.post(f"/api/courses/{cid}/notes", json={"title": "Goods", "body":
        "> **In one glance** free movement of goods\n"
        "1. **MEQR scope** — *Dassonville* (8/74) [WG]\n"
        "* the rule has *erga omnes* effect and is *not* optional\n\n"
        "| Case | Citation | Rule |\n|---|---|---|\n| *Cassis de Dijon* | 120/78 | mandatory requirements |\n"}).json()["id"]
    n2 = client.post(f"/api/courses/{cid}/notes", json={"title": "Keck revisited", "body": "*Keck* narrows *Dassonville* for selling arrangements [LECTURE]"}).json()["id"]
    cases = client.get(f"/api/courses/{cid}/cases").json()
    by = {c["name"]: c for c in cases}
    assert set(by) == {"Cassis de Dijon", "Dassonville", "Keck"}
    assert by["Cassis de Dijon"]["cite"] == "120/78"
    assert by["Dassonville"]["cite"] == "8/74"
    assert {n["id"] for n in by["Dassonville"]["notes"]} == {n1, n2}
    assert [n["title"] for n in by["Keck"]["notes"]] == ["Keck revisited"]


def test_case_index_empty_course(client):
    cid = client.post("/api/courses", json={"name": "Empty"}).json()["id"]
    assert client.get(f"/api/courses/{cid}/cases").json() == []


# ---------------------------------------------------------------- model-backed routes (fake client)
import json
import pathlib
import types
from datetime import timedelta

import psycopg
import pytest


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns queued replies and records every call."""
    def __init__(self, *replies):
        self.replies, self.calls, self.messages = list(replies), [], self

    def create(self, **kw):
        self.calls.append(kw)
        text, stop = self.replies.pop(0) if self.replies else (None, None)
        if text is None:
            raise AssertionError("unexpected model call")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason=stop or "end_turn", model="fake-model")


@pytest.fixture
def fake(monkeypatch):
    import run
    holder = {}
    def install(*replies):
        holder["c"] = FakeClient(*replies)
        monkeypatch.setattr(run, "client", lambda: holder["c"])
        return holder["c"]
    return install


def _upload(client, cid, name, text, week=""):
    return client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(text.encode()), "text/plain")}, data={"week": week}).json()["id"]


def _card(client, cid, front, back, week="", source="manual"):
    return client.post(f"/api/courses/{cid}/cards", json={"front": front, "back": back, "week": week, "source": source}).json()["id"]


def test_migration_006_backfills_card_week_from_source_file(client, pg):
    cid = _cid(client)
    _upload(client, cid, "W3 slides.txt", "Keck", week="3")
    kid = _card(client, cid, "Keck?", "Selling arrangements", source="W3 slides.txt")
    pg.execute("UPDATE cards SET week='' WHERE id=%s", (kid,)); pg.commit()
    sql = (pathlib.Path(__file__).parent.parent / "migrations" / "006_card_week.sql").read_text()
    update = [s for s in sql.split(";") if "UPDATE cards" in s][0].split("\n", 1)[1]  # drop the comment line
    pg.execute(update); pg.commit()
    assert pg.execute("SELECT week FROM cards WHERE id=%s", (kid,)).fetchone()[0] == "3"


def test_cards_filter_by_week_and_weak(client, pg):
    cid = _cid(client)
    a = _card(client, cid, "A", "a", week="1"); b = _card(client, cid, "B", "b", week="2"); c = _card(client, cid, "C", "c")
    pg.execute("UPDATE cards SET ease=1.96 WHERE id=%s", (b,)); pg.commit()
    ids = lambda qs: {x["id"] for x in client.get(f"/api/courses/{cid}/cards?x=1{qs}").json()}
    assert ids("") == {a, b, c}
    assert ids("&week=1") == {a}
    assert ids("&weak=1") == {b}
    assert ids("&week=2&weak=1") == {b} and ids("&week=1&weak=1") == set()


def test_generate_cards_takes_the_file_week(client, fake):
    import run
    cid = _cid(client)
    fid = _upload(client, cid, "handout.txt", "Cassis de Dijon: mandatory requirements", week="4")
    fc = fake((json.dumps([{"front": "Cassis?", "back": "Mandatory requirements"}, {"front": "Rule of reason?", "back": "Cassis"}]), None))
    assert client.post(f"/api/courses/{cid}/cards/generate", json={"file_id": fid, "count": 2}).json() == {"made": 2}
    assert {c["week"] for c in client.get(f"/api/courses/{cid}/cards").json()} == {"4"}
    assert fc.calls[0]["model"] == run.CHEAP_MODEL


def test_recall_map_weeks_due_ready_and_weak(client, pg):
    cid = _cid(client)
    _upload(client, cid, "w1.txt", "Art 34", week="1"); _upload(client, cid, "w10.txt", "Art 36", week="10")
    _card(client, cid, "Q1", "A1", week="1"); later = _card(client, cid, "Q2", "A2", week="2"); weak = _card(client, cid, "Q3", "A3")
    pg.execute("UPDATE cards SET due=%s WHERE id=%s", ((date.today() + timedelta(days=5)).isoformat(), later))
    pg.execute("UPDATE cards SET ease=2.0 WHERE id=%s", (weak,)); pg.commit()
    m = client.get(f"/api/courses/{cid}/recall-map").json()
    assert [w["week"] for w in m["weeks"]] == ["1", "2", "10", ""]
    by = {w["week"]: w for w in m["weeks"]}
    assert (by["1"]["due"], by["1"]["ready"], by["1"]["indexed"]) == (1, True, 1)
    assert (by["2"]["due"], by["2"]["ready"], by["2"]["indexed"]) == (0, True, 0)
    assert (by["10"]["ready"], by["10"]["indexed"]) == (False, 1)
    assert by[""]["due"] == 1 and m["weak"] == 1


def test_quiz_builds_four_options_from_cards(client, fake):
    import run
    cid = _cid(client)
    k0 = _card(client, cid, "Which case defines MEQRs?", "Dassonville", week="1")
    k1 = _card(client, cid, "Selling arrangements case?", "Keck", week="1")
    _card(client, cid, "Other week", "Not asked", week="2")
    # cards tie on due date and ease, so their order is random: item 0 always gets three usable answers, item 1 never does
    fc = fake((json.dumps([{"i": 0, "wrong": ["Cassis", "Gebhard", "Bosman"]}, {"i": 1, "wrong": ["Dassonville", "Keck", "Only"]}]), None))
    got = client.post(f"/api/courses/{cid}/quiz", json={"count": 8, "week": "1", "weak": 0}).json()
    assert fc.calls[0]["model"] == run.CHEAP_MODEL
    assert "Other week" not in fc.calls[0]["messages"][0]["content"]
    assert len(got) == 1  # the second item had too few distinct wrong answers once the right one was removed
    q = got[0]
    card_ids = {k0, k1}
    assert q["id"] in card_ids and len(q["options"]) == 4 and q["correct"] in q["options"] and len(set(q["options"])) == 4


def test_quiz_empty_scope_makes_no_model_call(client, fake):
    cid = _cid(client)
    fake()  # any call would raise
    assert client.post(f"/api/courses/{cid}/quiz", json={"week": "9"}).json() == []


def test_quiz_non_json_reply_is_502(client, fake):
    cid = _cid(client)
    _card(client, cid, "Q", "A")
    fake(("Sorry, I can't do that.", None))
    assert client.post(f"/api/courses/{cid}/quiz", json={}).status_code == 502


def test_infer_weeks_filename_first_then_model(client, fake, pg):
    import run
    cid = _cid(client)
    w2 = _upload(client, cid, "W2 slides.txt", "Dassonville")
    l3 = _upload(client, cid, "Lecture 03 transcript.txt", "Keck")
    rd = _upload(client, cid, "reader.txt", "Week four: justification and proportionality")
    sch = _upload(client, cid, "Schwarz notes.txt", "no week here")
    _card(client, cid, "Reader Q", "Reader A", source="reader.txt")
    fc = fake((json.dumps({rd: "4", sch: "", "not-a-file": "5"}), None))
    r = client.post(f"/api/courses/{cid}/infer-weeks").json()
    assert r == {"tagged": 3, "by_name": 2, "by_model": 1}
    weeks = {f["id"]: f["week"] for f in client.get(f"/api/courses/{cid}/files").json()}
    assert (weeks[w2], weeks[l3], weeks[rd], weeks[sch]) == ("2", "3", "4", "")
    assert fc.calls[0]["model"] == run.CHEAP_MODEL and w2 not in fc.calls[0]["messages"][0]["content"]
    assert pg.execute("SELECT week FROM cards WHERE source='reader.txt'").fetchone()[0] == "4"
    fake(("{}", None))
    assert client.post(f"/api/courses/{cid}/infer-weeks").json()["tagged"] == 0  # only Schwarz is left; model says no


# ---------------------------------------------------------------- Continue after a cut-off note
def _note_with_capture(client, cid):
    return client.post(f"/api/courses/{cid}/notes", json={"title": "Week 2", "body":
        "# Week 2\n**Scope** Art 34 [SLIDES]\n\n## Live capture — transcript 12 Sep\n[00:05] the lecturer corrected the Keck point <!--r:r1:5-->\n"}).json()["id"]


def test_reconcile_caps_at_8000_and_demands_a_bottom_line(client, fake):
    import run
    cid = _cid(client)
    nid = _note_with_capture(client, cid)
    fc = fake(("# Week 2 (reconciled)\n## Bottom line\n- Keck point corrected", None))
    r = client.post(f"/api/notes/{nid}/reconcile")
    assert r.status_code == 200, r.text
    call = fc.calls[0]
    assert call["max_tokens"] == run.RECONCILE_TOKENS == 8000
    assert call["model"] == run.STRONG_MODEL and "## Bottom line" in call["system"]
    assert "<!--cf:continue" not in client.get(f"/api/notes/{r.json()['id']}").json()["body"]


def test_continue_finishes_a_cut_off_reconcile(client, fake, pg):
    import run
    cid = _cid(client)
    src = _note_with_capture(client, cid)
    fc = fake(("# Week 2 (reconciled)\n## Core rules\n1. Dassonville — the scope test", "max_tokens"))
    new = client.post(f"/api/notes/{src}/reconcile").json()["id"]
    cut = client.get(f"/api/notes/{new}").json()["body"]
    assert cut.endswith(f"<!--cf:continue kind=reconcile src={src}-->")

    fc = fake(("is wide.\n## Bottom line\n- fix the Keck line first", None))
    r = client.post(f"/api/notes/{new}/continue")
    assert r.status_code == 200 and r.json()["cut"] is False
    body = client.get(f"/api/notes/{new}").json()["body"]
    assert "<!--cf:continue" not in body
    assert body.endswith("the scope test is wide.\n## Bottom line\n- fix the Keck line first")
    call = fc.calls[0]
    assert call["model"] == run.STRONG_MODEL and call["max_tokens"] == 8000
    assert [m["role"] for m in call["messages"]] == ["user"]  # no assistant prefill: current models reject it
    assert "ANSWER SO FAR:" in call["messages"][0]["content"] and "LIVE CAPTURE:" in call["messages"][0]["content"]
    assert pg.execute("SELECT COUNT(*) FROM note_versions WHERE note_id=%s", (new,)).fetchone()[0] == 1


def test_continue_marks_again_when_still_cut_off(client, fake):
    cid = _cid(client)
    src = _note_with_capture(client, cid)
    fake(("# partial", "max_tokens"))
    new = client.post(f"/api/notes/{src}/reconcile").json()["id"]
    fake(("more but still not done", "max_tokens"))
    assert client.post(f"/api/notes/{new}/continue").json()["cut"] is True
    assert "<!--cf:continue kind=reconcile" in client.get(f"/api/notes/{new}").json()["body"]


def test_continue_a_cut_off_draft_rebuilds_the_same_prompt(client, fake):
    import run
    cid = _cid(client)
    _upload(client, cid, "w5.txt", "Week five: proportionality", week="5")
    fake(("# Week 5 notes\n## Scope", "max_tokens"))
    nid = client.post(f"/api/courses/{cid}/notes/draft", json={"week": "5", "diagrams": False}).json()["id"]
    assert "<!--cf:continue kind=draft week=5 diagrams=0-->" in client.get(f"/api/notes/{nid}").json()["body"]
    fc = fake(("\n## Core rules\n1. Proportionality", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    call = fc.calls[0]
    assert call["model"] == run.CHEAP_MODEL and call["max_tokens"] == run.DRAFT_TOKENS
    assert "Week five: proportionality" in call["messages"][0]["content"]  # same files as the original draft


def test_continue_without_a_marker_is_400(client):
    cid = _cid(client)
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Fine", "body": "All done."}).json()["id"]
    r = client.post(f"/api/notes/{nid}/continue")
    assert r.status_code == 400 and "nothing to continue" in r.json()["detail"]
