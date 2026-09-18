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

    fc = fake((" is wide.\n## Bottom line\n- fix the Keck line first", None))
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
    fake(*[("# Week 5 notes\n## Scope", "max_tokens")] * run.DRAFT_ROUNDS)  # still cut after self-continuation
    nid = client.post(f"/api/courses/{cid}/notes/draft", json={"week": "5", "diagrams": False}).json()["id"]
    assert "<!--cf:continue kind=draft week=5 diagrams=0 files=" in client.get(f"/api/notes/{nid}").json()["body"]
    fc = fake(("\n## Core rules\n1. Proportionality", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    call = fc.calls[0]
    assert call["model"] == run.CHEAP_MODEL and call["max_tokens"] == run.DRAFT_TOKENS
    assert "Week five: proportionality" in call["messages"][0]["content"]  # same files as the original draft


def test_continue_without_a_marker_finishes_from_the_notes_own_text(client, fake):
    """A markerless note used to 400. It is now finished from its own text — that is this PR's point.

    Only notes written by draft/reconcile carry a marker, so everything pasted, imported or cut off
    upstream was unfinishable for good.
    """
    cid = _cid(client)
    _upload(client, cid, "w5.txt", "COURSE FILE MATERIAL")
    nid = client.post(f"/api/courses/{cid}/notes",
                      json={"title": "Imported", "body": "# Scope\nThe test is whether the measure"}).json()["id"]
    fc = fake((" restricts market access.", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    assert client.get(f"/api/notes/{nid}").json()["body"] == "# Scope\nThe test is whether the measure restricts market access."
    sent = fc.calls[0]["messages"][0]["content"]
    assert "The test is whether the measure" in sent          # the note's own text is the material
    assert "COURSE FILE MATERIAL" not in sent                  # and the ticked files are not read for this path


def test_continue_without_a_marker_never_auto_routes_above_the_notes_tier(client, fake):
    """Continue is a button, so this path is auto-routing.

    STRONG_MODEL is reconcile-only and may be set to Fable, which is ~10x a Sonnet call. Auto-routing
    must never reach it — see the model rules in CLAUDE.md.
    """
    import run
    cid = _cid(client)
    nid = client.post(f"/api/courses/{cid}/notes",
                      json={"title": "Imported", "body": "# Scope\nThe measure"}).json()["id"]
    fc = fake((" restricts access.", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    assert fc.calls[0]["model"] in (run.CHEAP_MODEL, run.MODEL)
    assert fc.calls[0]["max_tokens"] == run.DRAFT_TOKENS


def test_continue_an_empty_note_is_400(client):
    """The one case that still cannot be finished: there is nothing to finish from."""
    cid = _cid(client)
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Blank", "body": "   "}).json()["id"]
    r = client.post(f"/api/notes/{nid}/continue")
    assert r.status_code == 400 and "nothing to continue" in r.json()["detail"]


# ---------------------------------------------------------------- review fixes (PR #7)
def test_continue_joins_exactly_at_line_breaks_and_mid_word(client, fake):
    cid = _cid(client)
    src = _note_with_capture(client, cid)
    fake(("# Week 2 (reconciled)\n1. Keck narrows the scope\n", "max_tokens"))
    a = client.post(f"/api/notes/{src}/reconcile").json()["id"]
    fake(("## Bottom line\n- fix Keck", None))
    assert client.post(f"/api/notes/{a}/continue").status_code == 200
    assert client.get(f"/api/notes/{a}").json()["body"] == "# Week 2 (reconciled)\n1. Keck narrows the scope\n## Bottom line\n- fix Keck"
    fake(("# Week 2 (reconciled)\n1. *Dassonvi", "max_tokens"))
    b = client.post(f"/api/notes/{src}/reconcile").json()["id"]
    fc = fake(("lle* (8/74)\n", None))
    assert client.post(f"/api/notes/{b}/continue").status_code == 200
    assert client.get(f"/api/notes/{b}").json()["body"] == "# Week 2 (reconciled)\n1. *Dassonville* (8/74)"
    assert "begin with the exact next characters" in fc.calls[0]["messages"][0]["content"]


def test_continue_master_draft_uses_the_files_it_was_written_from(client, fake):
    cid = _cid(client)
    _upload(client, cid, "a.txt", "ALPHA material")
    b = _upload(client, cid, "b.txt", "BETA material")
    import run
    fake(*[("# Master notes\n## Scope\n", "max_tokens")] * run.DRAFT_ROUNDS)  # still cut after self-continuation
    nid = client.post(f"/api/courses/{cid}/notes/draft", json={"diagrams": True}).json()["id"]
    client.post(f"/api/files/{b}/toggle-to", json={"on": False})  # ticks change before Continue
    fc = fake(("## Core rules\n1. x", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    sent = fc.calls[0]["messages"][0]["content"]
    assert "ALPHA material" in sent and "BETA material" in sent


def test_continue_marker_survives_a_week_with_spaces(client, fake):
    cid = _cid(client)
    _upload(client, cid, "w3.txt", "WEEK THREE material", week="Week 3")
    import run
    fake(*[("# Week 3 notes\n", "max_tokens")] * run.DRAFT_ROUNDS)  # still cut after self-continuation
    nid = client.post(f"/api/courses/{cid}/notes/draft", json={"week": "Week 3", "diagrams": False}).json()["id"]
    assert "week=Week%203" in client.get(f"/api/notes/{nid}").json()["body"]
    fc = fake(("## Core rules", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    sent = fc.calls[0]["messages"][0]["content"]
    assert "WEEK THREE material" in sent and "week-Week 3" in sent


def test_infer_weeks_keeps_filename_tags_when_the_model_step_fails(client, fake, monkeypatch):
    import run
    from fastapi import HTTPException
    cid = _cid(client)
    w3 = _upload(client, cid, "W3 slides.txt", "Keck")
    other = _upload(client, cid, "notes.txt", "no week in here")
    fake(("not json at all", None))
    r = client.post(f"/api/courses/{cid}/infer-weeks")
    assert r.status_code == 200
    body = r.json()
    assert (body["tagged"], body["by_name"], body["by_model"]) == (1, 1, 0) and "warning" in body
    weeks = {f["id"]: f["week"] for f in client.get(f"/api/courses/{cid}/files").json()}
    assert (weeks[w3], weeks[other]) == ("3", "")
    def no_key():
        raise HTTPException(400, "ANTHROPIC_API_KEY not set — add it to .env and restart.")
    monkeypatch.setattr(run, "client", no_key)
    _upload(client, cid, "Week 4 reader.txt", "Cassis")
    r = client.post(f"/api/courses/{cid}/infer-weeks").json()
    assert r["by_name"] == 1 and "ANTHROPIC_API_KEY" in r["warning"]


def test_quiz_ignores_distractors_that_are_not_a_list(client, fake):
    cid = _cid(client)
    _card(client, cid, "Which article?", "Article 34 TFEU")
    fake((json.dumps([{"i": 0, "wrong": "Art 30; Art 36; Art 45"}]), None))
    assert client.post(f"/api/courses/{cid}/quiz", json={}).json() == []


# ---------------------------------------------------------------- spoken answer to your own question (Phase 12)
GRADE_SHAKY = json.dumps({"mastery": "shaky", "verdict": "Right mode, missed the theft rule",
                          "spoken": "You named production. But Fruity took the apples knowingly, so what does 5:201(2) do?",
                          "note": "Missed VIII.-5:201(2): a producer who knowingly takes the material does not become owner."})
NOTE = ("## Production\nVIII.-5:201: the producer becomes owner.<!--r:abc123:12--> "
        "Not where the producer knowingly acts without consent (5:201(2)).")


def _speech(client, **body):
    return client.post("/api/speech", json={"question": "Who owns juice made from stolen apples?",
                                            "answer": "Fruity, because it produced the juice.", "notes": NOTE, **body})


def test_speech_needs_a_question_and_an_answer_before_any_model_call(client, fake):
    fc = fake()
    assert _speech(client, answer="   ").status_code == 400
    assert _speech(client, question="  ").status_code == 400
    assert client.post("/api/speech", json={"question": "Q", "notes": NOTE}).status_code == 422
    assert client.post("/api/speech", json={"answer": "A", "notes": NOTE}).status_code == 422
    assert fc.calls == []


def test_speech_without_a_reference_is_labelled_outside_the_files(client, fake):
    fc = fake((GRADE_SHAKY, None))
    assert _speech(client, notes="  <!--r:only-an-anchor:1-->  ").status_code == 200  # an anchor alone is no reference
    msg = fc.calls[0]["messages"][0]["content"]
    assert "REFERENCE: none supplied" in msg and "[OUTSIDE FILES]" in msg
    assert "THE STUDENT'S OWN NOTE" not in msg and "MODEL ANSWER" not in msg


def test_speech_can_grade_against_a_model_answer(client, fake):
    fc = fake((GRADE_SHAKY, None))
    assert _speech(client, notes="", model_answer="The material owners, under VIII.-5:201(2).").status_code == 200
    msg = fc.calls[0]["messages"][0]["content"]
    assert "MODEL ANSWER: The material owners" in msg and "REFERENCE: none supplied" not in msg
    assert msg.index("QUESTION:") < msg.index("MODEL ANSWER:") < msg.index("STUDENT'S SPOKEN ANSWER")


def test_speech_grades_against_the_note_with_the_shared_cached_grader(client, fake):
    import run
    fc = fake((GRADE_SHAKY, None))
    r = _speech(client)
    assert r.status_code == 200
    want = json.loads(GRADE_SHAKY)
    assert r.json() == {"mastery": "shaky", "verdict": want["verdict"], "spoken": want["spoken"], "note": want["note"], "rating": 1}
    call = fc.calls[0]
    assert call["system"] == run._grader_system()
    assert call["system"][-1]["cache_control"] == {"type": "ephemeral"}
    msg = call["messages"][0]["content"]
    assert msg.index("Who owns juice") < msg.index("THE STUDENT'S OWN NOTE") < msg.index("Fruity, because")
    assert "VIII.-5:201" in msg and "<!--" not in msg        # recording anchors are not course content
    assert "COMMON TRAPS" not in msg and "MODEL ANSWER" not in msg and "REFERENCE: none" not in msg
    assert call["model"] == run.pick_model("drill", None)    # auto-routed; the caller cannot choose


def test_speech_caps_what_it_sends(client, fake):
    import run
    fc = fake((GRADE_SHAKY, None))
    assert _speech(client, question="µ" * 5000, answer="¶" * 9000, notes="§" * 50000, model_answer="¤" * 9000).status_code == 200
    msg = fc.calls[0]["messages"][0]["content"]
    assert (msg.count("µ"), msg.count("¶"), msg.count("§"), msg.count("¤")) == (
        run.SPEECH_QUESTION_CHARS, run.SPEECH_ANSWER_CHARS, run.SPEECH_NOTES_CHARS, run.SPEECH_ANSWER_CHARS)


def test_speech_never_trusts_an_unexpected_grade(client, fake):
    fake((json.dumps({"mastery": "brilliant", "verdict": "Top marks"}), None))
    r = _speech(client)
    assert r.status_code == 200 and (r.json()["mastery"], r.json()["rating"]) == ("missed", 0)


def test_speech_reports_grader_failures(client, fake):
    fake(("not json at all", None))
    assert _speech(client).status_code == 502
    fake()  # nothing queued: the fake raises, the way a network failure would
    assert _speech(client).status_code == 502


def test_speech_without_an_api_key_says_so(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = _speech(client)
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_speech_writes_nothing(client, fake, pg):
    cid = _cid(client)
    kid = _card(client, cid, "Who owns juice made from stolen apples?", "The material owners (VIII.-5:201(2)).")
    snapshot = lambda: pg.execute("SELECT due, reps, interval, (SELECT count(*) FROM reviews) FROM cards WHERE id=%s", (kid,)).fetchone()
    before = snapshot()
    fake((GRADE_SHAKY, None))
    assert _speech(client).status_code == 200
    assert snapshot() == before  # no card behind the question, so nothing is reviewed or rescheduled


def test_speech_and_card_grading_share_one_cached_prompt(client, fake):
    cid = _cid(client)
    kid = _card(client, cid, "Who owns juice made from stolen apples?", "The material owners (VIII.-5:201(2)).")
    fc = fake((GRADE_SHAKY, None), (GRADE_SHAKY, None))
    assert client.post(f"/api/courses/{cid}/oral/grade", json={"card_id": kid, "answer": "Fruity."}).status_code == 200
    assert _speech(client).status_code == 200
    card_call, own_call = fc.calls
    assert card_call["system"] == own_call["system"] and card_call["model"] == own_call["model"]


def test_speak_returns_audio_or_tells_the_page_to_speak_itself(client, monkeypatch):
    import tts
    monkeypatch.setattr(tts, "say", lambda text: None)
    assert client.post("/api/speak", json={"text": "Hello."}).status_code == 204
    monkeypatch.setattr(tts, "say", lambda text: (b"ID3fake-mp3", "audio/mpeg"))
    r = client.post("/api/speak", json={"text": "Hello."})
    assert r.status_code == 200 and r.content == b"ID3fake-mp3"
    assert r.headers["content-type"] == "audio/mpeg" and r.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- syllabus in, weeks and topics out (Phase 13)
SYLLABUS_TEXT = (
    "Course guide 2026/27 — European Law\n"
    "Week 1: Free movement of goods. Tariff barriers; MEQRs. Reading: Schutze, ch. 12.\n"
    "Week 2: Justification and proportionality. Art 36; mandatory requirements. Reading: Schutze, ch. 13, par. 4-9.\n"
)
SYLLABUS_REPLY = json.dumps({"weeks": [
    {"week": 1, "title": "Free movement of goods", "topics": ["Tariff barriers", "MEQRs"],
     "readings": [{"author": "Schutze", "title": "European Union Law", "chapters": "ch. 12"}]},
    {"week": "Week 2", "title": "Justification and proportionality", "topics": ["Article 36", "Mandatory requirements"],
     "readings": ["Schutze, ch. 13, par. 4-9"]}],
    "note": "A two-week course guide."})


def _syllabus(client, cid, fake, reply=SYLLABUS_REPLY, name="Course guide.txt", text=SYLLABUS_TEXT):
    fid = _upload(client, cid, name, text)
    fc = fake((reply, None))
    r = client.post(f"/api/courses/{cid}/syllabus/extract", json={"file_id": fid})
    return fid, fc, r


def test_syllabus_extract_proposes_weeks_and_writes_nothing(client, fake, pg):
    cid = _cid(client)
    fid, fc, r = _syllabus(client, cid, fake)
    assert r.status_code == 200
    got = r.json()
    assert [w["week"] for w in got["weeks"]] == ["1", "2"]
    assert got["weeks"][0]["title"] == "Free movement of goods"
    assert got["weeks"][0]["topics"] == ["Tariff barriers", "MEQRs"]
    assert got["weeks"][0]["readings"] == ["Schutze — European Union Law, ch. 12"]   # the object shape is flattened
    assert got["weeks"][1]["week"] == "2" and got["note"] == "A two-week course guide."
    assert SYLLABUS_TEXT.strip() in fc.calls[0]["messages"][0]["content"]
    # nothing written: no week on the file it read, nothing under brief.syllabus
    assert {f["week"] for f in client.get(f"/api/courses/{cid}/files").json()} == {""}
    assert (pg.execute("SELECT brief FROM courses WHERE id=%s", (cid,)).fetchone()[0] or {}).get("syllabus") is None
    assert client.get(f"/api/courses/{cid}/syllabus").json() == {"weeks": [], "source": ""}


def test_syllabus_extraction_never_reaches_the_strong_model(client, fake, monkeypatch):
    """CF_STRONG_MODEL is reconcile-only, and Fable sits behind it. Structured extraction from one document is
    the cheap tier's job, and there is no model parameter on the route that could override that."""
    import run
    monkeypatch.setattr(run, "STRONG_MODEL", "claude-fable-5-1")
    cid = _cid(client)
    _, fc, r = _syllabus(client, cid, fake)
    assert r.status_code == 200
    assert [c["model"] for c in fc.calls] == [run.CHEAP_MODEL]
    assert run.STRONG_MODEL not in [c["model"] for c in fc.calls]
    assert r.json()["model"] == run.CHEAP_MODEL
    # the route asks pick_model for "summarise", and no document text can escalate that to the strong model
    for text in ("", "compare and contrast", "why does this diverge", "write an exam answer"):
        assert run.pick_model("summarise", None, text) != run.STRONG_MODEL
    assert "model" not in run.SyllabusExtractIn.model_fields   # nothing to request a model with


def test_a_document_that_is_not_a_syllabus_invents_no_weeks(client, fake):
    cid = _cid(client)
    reply = json.dumps({"weeks": [], "note": "This reads as a judgment, not a course guide."})
    _, _, r = _syllabus(client, cid, fake, reply=reply, name="Dassonville.txt", text="Judgment of the Court, 11 July 1974")
    assert r.status_code == 200 and r.json()["weeks"] == []
    assert r.json()["note"] == "This reads as a judgment, not a course guide."


def test_a_malformed_syllabus_reply_is_502_not_a_traceback(client, fake):
    cid = _cid(client)
    fid = _upload(client, cid, "guide.txt", SYLLABUS_TEXT)
    for reply in ("Sorry, I can't do that.", json.dumps(["week 1", "week 2"]), json.dumps({"weeks": "week one"})):
        fake((reply, None))
        r = client.post(f"/api/courses/{cid}/syllabus/extract", json={"file_id": fid})
        assert r.status_code == 502, reply
        assert r.json()["detail"] and "Traceback" not in r.json()["detail"]
    fake()  # an image has no text, so no model call may be made at all
    img = client.post(f"/api/courses/{cid}/files", files={"file": ("scan.png", io.BytesIO(b"\x89PNG"), "image/png")}).json()["id"]
    assert client.post(f"/api/courses/{cid}/syllabus/extract", json={"file_id": img}).status_code == 422
    assert client.post(f"/api/courses/{cid}/syllabus/extract", json={"file_id": "nope"}).status_code == 404


def test_syllabus_apply_stores_weeks_and_tags_only_unambiguous_files(client, fake, pg):
    cid = _cid(client)
    _, _, r = _syllabus(client, cid, fake)
    weeks = r.json()["weeks"]
    by_number = _upload(client, cid, "W2 handout.txt", "Art 36")
    by_title = _upload(client, cid, "Free movement of goods - slides.txt", "Dassonville")
    already = _upload(client, cid, "W1 seminar.txt", "MEQRs", week="9")
    neither = _upload(client, cid, "Schwarz notes.txt", "no week here")
    _card(client, cid, "Q", "A", source="W2 handout.txt")
    out = client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": weeks, "source": "Course guide.txt"}).json()
    assert out["weeks"] == 2 and out["tagged"] == 2
    got = {f["id"]: f["week"] for f in client.get(f"/api/courses/{cid}/files").json()}
    assert got[by_number] == "2" and got[by_title] == "1"
    assert got[already] == "9"      # an existing week is never overwritten
    assert got[neither] == ""       # nothing in the name names a week
    assert pg.execute("SELECT week FROM cards WHERE source='W2 handout.txt'").fetchone()[0] == "2"
    stored = pg.execute("SELECT brief FROM courses WHERE id=%s", (cid,)).fetchone()[0]["syllabus"]
    assert [w["week"] for w in stored["weeks"]] == ["1", "2"] and stored["source"] == "Course guide.txt"
    assert client.get(f"/api/courses/{cid}/syllabus").json() == stored


def test_syllabus_apply_leaves_a_file_two_weeks_could_claim_alone(client, fake):
    """The filename says week 1 and the title of week 2 is in it. Two answers is not an unambiguous match."""
    cid = _cid(client)
    _, _, r = _syllabus(client, cid, fake)
    fid = _upload(client, cid, "W1 justification and proportionality.txt", "Art 36")
    client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": r.json()["weeks"]})
    assert next(f["week"] for f in client.get(f"/api/courses/{cid}/files").json() if f["id"] == fid) == ""


def test_re_applying_the_same_syllabus_changes_nothing(client, fake, pg):
    cid = _cid(client)
    _, _, r = _syllabus(client, cid, fake)
    weeks = r.json()["weeks"]
    _upload(client, cid, "W2 handout.txt", "Art 36")
    state = lambda: (pg.execute("SELECT brief,tutor_prompt FROM courses WHERE id=%s", (cid,)).fetchone(),
                     sorted((f["id"], f["week"]) for f in client.get(f"/api/courses/{cid}/files").json()))
    first = client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": weeks}).json()
    pg.commit(); after_one = state()
    again = client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": weeks}).json()
    pg.commit(); assert state() == after_one
    client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": list(reversed(weeks))})
    pg.commit(); assert state() == after_one          # order in the payload does not matter
    assert first["tagged"] == 1 and again["tagged"] == 0   # the second run has nothing left to tag
    assert (again["weeks"], again["tutor_prompt"]) == (first["weeks"], first["tutor_prompt"])
    assert after_one[0][1].count("COURSE SCHEDULE (from the syllabus):") == 1


def test_applying_an_empty_syllabus_takes_the_schedule_back_out(client, fake, pg):
    cid = _cid(client)
    _, _, r = _syllabus(client, cid, fake)
    before = pg.execute("SELECT tutor_prompt FROM courses WHERE id=%s", (cid,)).fetchone()[0]
    client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": r.json()["weeks"]})
    assert client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": []}).json()["weeks"] == 0
    pg.commit()
    brief, prompt = pg.execute("SELECT brief,tutor_prompt FROM courses WHERE id=%s", (cid,)).fetchone()
    assert "syllabus" not in brief and prompt == before


def test_syllabus_topics_reach_the_tutor_prompt(client, fake):
    import course_brief as cb
    cid = _cid(client)
    _, _, r = _syllabus(client, cid, fake)
    prompt = client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": r.json()["weeks"]}).json()["tutor_prompt"]
    assert prompt == next(c["tutor_prompt"] for c in client.get("/api/courses").json() if c["id"] == cid)
    assert "Week 1 — Free movement of goods. Topics: Tariff barriers; MEQRs." in prompt
    assert "Reading: Schutze — European Union Law, ch. 12." in prompt
    assert prompt.startswith("Course specifics — European Law")   # the compiled brief is still in front of it
    assert cb.syllabus_block({"syllabus": client.get(f"/api/courses/{cid}/syllabus").json()}) in prompt


def test_a_hand_written_prompt_keeps_its_text_and_gains_the_schedule(client, fake):
    cid = client.post("/api/courses", json={"name": "Legacy", "tutor_prompt": "hand-written"}).json()["id"]
    _, _, r = _syllabus(client, cid, fake)
    prompt = client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": r.json()["weeks"]}).json()["tutor_prompt"]
    assert prompt.startswith("hand-written\nCOURSE SCHEDULE (from the syllabus):")
    pv = client.post("/api/course-brief/preview", json={"name": "Legacy", "brief": {}, "cid": cid}).json()
    assert pv["fallback"] is True and pv["prompt"] == prompt


def test_saving_course_settings_does_not_wipe_an_applied_syllabus(client, fake, pg):
    """The course dialog has no syllabus fields, so the brief it posts carries none. Without keep_syllabus,
    pressing Save changes on any course silently threw the applied schedule away."""
    cid = _cid(client)
    _, _, r = _syllabus(client, cid, fake)
    client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": r.json()["weeks"]})
    pg.commit()
    brief = dict(pg.execute("SELECT brief FROM courses WHERE id=%s", (cid,)).fetchone()[0])
    brief.pop("syllabus")
    saved = client.put(f"/api/courses/{cid}", json={"name": "European Law", "brief": brief}).json()["tutor_prompt"]
    assert "COURSE SCHEDULE (from the syllabus):" in saved
    pg.commit()
    assert pg.execute("SELECT brief FROM courses WHERE id=%s", (cid,)).fetchone()[0]["syllabus"]["weeks"]


def test_infer_weeks_is_untouched_by_the_syllabus_routes(client, fake):
    """This is an addition, not a replacement: infer-weeks still reads filenames and still calls the cheap model."""
    import run
    cid = _cid(client)
    w2 = _upload(client, cid, "W2 slides.txt", "Dassonville")
    rd = _upload(client, cid, "reader.txt", "Week four: proportionality")
    fc = fake((json.dumps({rd: "4"}), None))
    assert client.post(f"/api/courses/{cid}/infer-weeks").json() == {"tagged": 2, "by_name": 1, "by_model": 1}
    assert fc.calls[0]["model"] == run.CHEAP_MODEL
    weeks = {f["id"]: f["week"] for f in client.get(f"/api/courses/{cid}/files").json()}
    assert (weeks[w2], weeks[rd]) == ("2", "4")
# ---------------------------------------------------------------- Phase 14: notes you can listen to
import re
import threading
import time

import storage
import tts

NOTE_BODY = (
    "# Free movement of goods\n\n"
    "> **In one glance** Article 34 catches measures having equivalent effect. [SLIDES]\n\n"
    "## The Dassonville formula\n"
    "1. **All trading rules** capable of hindering trade are caught — *Dassonville* (8/74) [WG]\n"
    "2. *Keck* carves out selling arrangements [LECTURE] <!--r:abc0123456:42-->\n\n"
    "```mermaid\nflowchart TD\n  A[Measure] --> B[Caught by Art 34?]\n```\n\n"
    "## Derogations\n"
    "| Case | Rule |\n|---|---|\n| *Cassis de Dijon* | mandatory requirements |\n"
)

SCRIPT = ("Free movement of goods. In one glance: Article thirty-four catches measures having equivalent "
          "effect. The Dassonville formula. All trading rules capable of hindering trade are caught, "
          "Dassonville, eight of seventy-four. Keck carves out selling arrangements. Derogations. "
          "Cassis de Dijon gives the mandatory requirements.")


@pytest.fixture
def voice(monkeypatch):
    """A voice that answers without leaving the process, the way `fake` answers for the model.
    narrate() still does its own chunking and joining — only synthesising one line is stood in for."""
    said, gate = [], threading.Event()
    gate.set()

    def say(line):
        gate.wait(10)
        said.append(line)
        return b"ID3" + line.encode()[:24], "audio/mpeg"

    monkeypatch.setattr(tts, "BACKEND", "test")
    monkeypatch.setattr(tts, "available", lambda: True)
    monkeypatch.setattr(tts, "say", say)
    return types.SimpleNamespace(said=said, gate=gate)


def _note(client, cid, body=NOTE_BODY, title="Goods"):
    return client.post(f"/api/courses/{cid}/notes", json={"title": title, "body": body}).json()["id"]


def _audio(client, nid):
    return client.get(f"/api/notes/{nid}/audio").json()


def _wait_audio(client, nid, timeout=15):
    """The generation runs off the request thread, so the test polls the job the way the page does."""
    end = time.time() + timeout
    while time.time() < end:
        s = _audio(client, nid)
        if s["status"] not in ("queued", "running"):
            return s
        time.sleep(0.05)
    raise AssertionError(f"the reading never finished: {_audio(client, nid)}")


def _key(pg, nid):
    pg.commit()  # the job committed on another connection; drop this one's snapshot first
    row = pg.execute("SELECT key FROM note_audio WHERE note_id=%s", (nid,)).fetchone()
    return row[0] if row else None


def test_asking_for_audio_returns_a_job_and_records_nothing_in_the_request(client, fake, voice, pg):
    """A long note is minutes of speech. The request hands back a job and the page polls it."""
    nid = _note(client, _cid(client))
    fake((SCRIPT, None))
    voice.gate.clear()                                     # hold the voice mid-generation
    started = client.post(f"/api/notes/{nid}/audio").json()
    assert started["status"] in ("queued", "running") and started["ready"] is False
    pg.commit()
    assert pg.execute("SELECT count(*) FROM note_audio").fetchone()[0] == 0, "audio was written synchronously"
    job = pg.execute("SELECT status, executor FROM jobs WHERE ref_id=%s AND kind='note_audio'", (nid,)).fetchone()
    assert job is not None, "the state of a running generation must live in `jobs`"
    voice.gate.set()
    done = _wait_audio(client, nid)
    assert (done["status"], done["ready"]) == ("ready", True)
    assert done["bytes"] > 0 and done["chars"] == len(SCRIPT)


def test_the_script_is_the_notes_own_words_and_leaves_out_what_cannot_be_heard(client, fake, voice):
    import run
    nid = _note(client, _cid(client))
    fc = fake((SCRIPT + " [WG] **bold** [LECTURE]", None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"

    call = fc.calls[0]
    assert call["model"] == run.CHEAP_MODEL, "the script writer is CF_CHEAP_MODEL, never the strong model"
    shown = call["messages"][0]["content"]
    assert "mermaid" not in shown and "flowchart" not in shown, "a diagram read aloud is a minute of punctuation"
    assert "<!--" not in shown, "recording anchors are not course content"
    assert "The Dassonville formula" in shown and "Derogations" in shown
    assert shown.index("Dassonville formula") < shown.index("Derogations"), "the headings keep the note's order"
    assert "Say only what the note says" in call["system"]

    spoken = " ".join(voice.said)
    assert "[WG]" not in spoken and "[LECTURE]" not in spoken and "**" not in spoken
    assert "Dassonville" in spoken and "Cassis de Dijon" in spoken


def test_an_unchanged_note_is_not_read_a_second_time(client, fake, voice, pg):
    nid = _note(client, _cid(client))
    fc = fake((SCRIPT, None))                    # one reply queued: a second script call would raise
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"
    key = _key(pg, nid)

    again = client.post(f"/api/notes/{nid}/audio").json()
    assert again["status"] == "ready" and again["ready"] is True
    assert len(fc.calls) == 1 and len(voice.said) > 0
    assert _key(pg, nid) == key, "the existing key is returned, not a second recording"


def test_editing_the_note_invalidates_the_reading(client, fake, voice, pg):
    nid = _note(client, _cid(client))
    fake((SCRIPT, None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"
    old = _key(pg, nid)
    assert storage.exists(old)

    client.put(f"/api/notes/{nid}", json={"title": "Goods", "body": NOTE_BODY + "\n3. *Gebhard* on establishment [WG]\n"})
    stale = _audio(client, nid)
    assert (stale["ready"], stale["stale"], stale["status"]) == (False, True, "none")

    fake((SCRIPT + " Gebhard covers establishment.", None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"
    new = _key(pg, nid)
    assert new != old and storage.exists(new)
    assert not storage.exists(old), "the superseded reading is not left in the bucket"


def test_a_failure_is_a_job_in_error_that_gives_nothing_away(client, fake, voice, monkeypatch, pg):
    nid = _note(client, _cid(client))
    fake((SCRIPT, None))
    monkeypatch.setattr(tts, "say", lambda line: None)          # the voice goes quiet part-way
    client.post(f"/api/notes/{nid}/audio")
    s = _wait_audio(client, nid)

    assert (s["status"], s["ready"]) == ("failed", False)
    assert s["error"] == "The voice stopped part-way through the note."
    for leak in ("notes/", "spoken/", "Traceback", "bucket", nid):
        assert leak not in s["error"]
    pg.commit()
    assert pg.execute("SELECT count(*) FROM note_audio").fetchone()[0] == 0

    fake((SCRIPT, None))                                        # and it can simply be asked again
    monkeypatch.setattr(tts, "say", lambda line: (b"ID3ok", "audio/mpeg"))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"


def test_the_reading_is_stored_through_storage_under_its_own_prefix(client, fake, voice, pg):
    """`recordings` is audio the student made; this is audio the app made, and it gets its own prefix."""
    nid = _note(client, _cid(client))
    fake((SCRIPT, None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"

    key = _key(pg, nid)
    assert key.startswith(f"notes/{nid}/spoken/") and key.endswith(".mp3")
    assert key != f"notes/{nid}/audio", "the student's own recordings keep notes/{nid}/audio"
    assert storage.exists(key)

    r = client.get(f"/api/notes/{nid}/audio/file")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == storage.get(key)
    assert client.get("/api/notes/nope/audio/file").status_code == 404


def test_a_reading_whose_process_died_stays_readable_and_can_be_asked_again(client, fake, voice, pg):
    import run
    nid = _note(client, _cid(client))
    fake((SCRIPT, None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"

    # the app restarts mid-generation: the job row is all that is left, and it is still readable
    pg.execute("DELETE FROM note_audio WHERE note_id=%s", (nid,))
    pg.execute("UPDATE jobs SET status='running', stage='recording', updated=%s WHERE ref_id=%s AND kind='note_audio'",
               (time.time(), nid))
    pg.commit()
    live = _audio(client, nid)
    assert (live["status"], live["stage"], live["ready"]) == ("running", "recording", False)

    # nothing in this process will ever finish it, so once it is old enough it is collected
    pg.execute("UPDATE jobs SET updated=%s WHERE ref_id=%s AND kind='note_audio'",
               (time.time() - run.SPOKEN_STALE_S - 1, nid))
    pg.commit()
    collected = _audio(client, nid)
    assert collected["status"] == "failed" and "press Listen" in collected["error"]

    fake((SCRIPT, None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"


def test_deleting_the_note_takes_its_reading_with_it(client, fake, voice, pg):
    nid = _note(client, _cid(client))
    fake((SCRIPT, None))
    client.post(f"/api/notes/{nid}/audio")
    assert _wait_audio(client, nid)["status"] == "ready"
    key = _key(pg, nid)

    assert client.delete(f"/api/notes/{nid}").status_code == 200
    assert not storage.exists(key), "an object nothing can point at any more is still the student's content"
    pg.commit()
    assert pg.execute("SELECT count(*) FROM note_audio WHERE note_id=%s", (nid,)).fetchone()[0] == 0
    assert pg.execute("SELECT count(*) FROM jobs WHERE ref_id=%s", (nid,)).fetchone()[0] == 0


def test_a_reading_needs_a_voice_and_something_to_read(client, fake, voice, monkeypatch):
    cid = _cid(client)
    fake()                                              # any model call at all would raise
    blank = _note(client, cid, "```mermaid\nflowchart TD\n  A[only a diagram]\n```\n", "Blank")
    assert client.post(f"/api/notes/{blank}/audio").status_code == 400

    nid = _note(client, cid)
    monkeypatch.setattr(tts, "available", lambda: False)
    r = client.post(f"/api/notes/{nid}/audio")
    assert r.status_code == 400 and "voice" in r.json()["detail"]
    assert client.post("/api/notes/nope/audio").status_code == 404


# ---- the play control on the page (no JS runner here, so this reads the sheet the way the other UI tests do)
_ST = pathlib.Path(__file__).parent.parent / "static"
_rd = lambda n: (_ST / n).read_text(encoding="utf-8")
# index.html was split into markup + app.js + two sheets; read the page as the browser assembles it.
NOTES_PAGE = _rd("index.html") + _rd("app.js")
NOTES_CSS = re.sub(r"/\*.*?\*/", "", _rd("app.css") + _rd("book.css") + _rd("app-after.css"), flags=re.S)


def test_the_play_control_clears_the_quality_floor():
    assert 'id="listenBtn"' in NOTES_PAGE and 'id="listenAudio"' in NOTES_PAGE
    # .btn.small is where min-height/min-width:var(--tap) lives, so the 32px floor comes with the class
    assert 'class="btn small ghost listen" id="listenBtn"' in NOTES_PAGE
    assert ".listen:focus-visible{outline:2px solid var(--accent)" in NOTES_CSS
    anim = NOTES_CSS.index(".listen[data-listen=working]::before")
    reduce = NOTES_CSS.index("@media(prefers-reduced-motion:reduce){.listen[data-listen=working]::before")
    assert reduce > anim, "at equal specificity the reduce block has to come last or it loses the cascade"


def test_the_note_views_hooks_and_renderer_are_untouched():
    """CLAUDE.md: keep every id and data- attribute, and leave render/chipify/priomark alone."""
    for hook in ('id="noteView"', 'id="readbar"', 'id="recList"', 'id="noteBody"', 'data-cover="off"', 'id="cleanBtn"'):
        assert hook in NOTES_PAGE, f"{hook} disappeared — a hook was renamed"
    for fn in ("function chipify(", "function priomark(", "async function paint("):
        assert fn in NOTES_PAGE
