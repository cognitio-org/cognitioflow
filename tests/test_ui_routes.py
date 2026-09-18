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


# ---------------------------------------------------------------- Phase 16: the case law, in order
def _timeline_note(client, cid):
    return client.post(f"/api/courses/{cid}/notes", json={"title": "Supremacy", "body":
        "1. **Direct effect** — *Van Gend en Loos* (26/62) [LECTURE]\n"
        "2. **Primacy** — *Costa v ENEL* (6/64) [LECTURE]\n"
        "3. **Set aside** — *Simmenthal* (106/77) [WG]\n"
        "4. **Read together with** *Factortame* (ECLI:EU:C:1990:257) [WG]\n"
        "5. *Melloni* is on the reading list but I never wrote its citation down [SLIDES]\n\n"
        "| Case | Citation | Year | Rule |\n|---|---|---|---|\n"
        "| *Cassis de Dijon* | 120/78 | 1979 | mandatory requirements |\n"}).json()["id"]


def test_cases_carry_the_year_the_notes_wrote(client):
    """The year is read off the citation as written — ECLI, a four-figure year, or the year in an EU
    case number. A case the notes never dated stays undated: the model's own memory is not a source."""
    cid = _cid(client)
    _timeline_note(client, cid)
    by = {c["name"]: c for c in client.get(f"/api/courses/{cid}/cases").json()}
    assert by["Van Gend en Loos"]["year"] == 1962
    assert by["Costa v ENEL"]["year"] == 1964
    assert by["Simmenthal"]["year"] == 1977
    assert by["Factortame"]["year"] == 1990          # ECLI year field
    assert by["Cassis de Dijon"]["year"] == 1979     # the table's own Year column, not 1978 from 120/78
    assert by["Melloni"]["year"] is None             # a famous case, and still undated here


def test_timeline_orders_by_year_and_groups_the_undated(client):
    cid = _cid(client)
    _timeline_note(client, cid)
    t = client.get(f"/api/courses/{cid}/timeline").json()
    assert [g["year"] for g in t["groups"]] == [1962, 1964, 1977, 1979, 1990]
    assert [c["name"] for g in t["groups"] for c in g["cases"]] == [
        "Van Gend en Loos", "Costa v ENEL", "Simmenthal", "Cassis de Dijon", "Factortame"]
    assert [c["name"] for c in t["undated"]] == ["Melloni"]     # listed, not interleaved by guess
    assert t["span"] == {"from": 1962, "to": 1990} and t["total"] == 6
    # the note it came from is reachable from the timeline, as it is from the A-Z index
    assert all(c["notes"] for g in t["groups"] for c in g["cases"])


def test_timeline_same_year_keeps_a_stable_order(client):
    cid = _cid(client)
    client.post(f"/api/courses/{cid}/notes", json={"title": "1974", "body":
        "*Reyners* (2/74) and *Dassonville* (8/74) and *Van Binsbergen* (33/74) [WG]"})
    seen = [[c["name"] for c in client.get(f"/api/courses/{cid}/timeline").json()["groups"][0]["cases"]]
            for _ in range(3)]
    assert seen[0] == ["Dassonville", "Reyners", "Van Binsbergen"] and seen[1] == seen[0] == seen[2]


def test_timeline_of_a_course_with_no_cases_is_empty_not_an_error(client):
    cid = client.post("/api/courses", json={"name": "Empty"}).json()["id"]
    r = client.get(f"/api/courses/{cid}/timeline")
    assert r.status_code == 200
    assert r.json() == {"groups": [], "undated": [], "total": 0, "span": None}


def test_timeline_holds_the_case_index_line_on_outside_files(client):
    """[OUTSIDE FILES] on a new surface: only what the course wrote down gets on the timeline."""
    cid = _cid(client)
    client.post(f"/api/courses/{cid}/notes", json={"title": "Goods", "body": "*Keck* (C-267/91) [WG]"})
    t = client.get(f"/api/courses/{cid}/timeline").json()
    names = {c["name"] for g in t["groups"] for c in g["cases"]} | {c["name"] for c in t["undated"]}
    assert names == {"Keck"}          # not Cassis, not Dassonville — the notes never name them
    assert t["groups"][0]["year"] == 1991


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
    fake(("# Week 5 notes\n## Scope", "max_tokens"))
    nid = client.post(f"/api/courses/{cid}/notes/draft", json={"week": "5", "diagrams": False}).json()["id"]
    assert "<!--cf:continue kind=draft week=5 diagrams=0 files=" in client.get(f"/api/notes/{nid}").json()["body"]
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
    fake(("# Master notes\n## Scope\n", "max_tokens"))
    nid = client.post(f"/api/courses/{cid}/notes/draft", json={"diagrams": True}).json()["id"]
    client.post(f"/api/files/{b}/toggle-to", json={"on": False})  # ticks change before Continue
    fc = fake(("## Core rules\n1. x", None))
    assert client.post(f"/api/notes/{nid}/continue").status_code == 200
    sent = fc.calls[0]["messages"][0]["content"]
    assert "ALPHA material" in sent and "BETA material" in sent


def test_continue_marker_survives_a_week_with_spaces(client, fake):
    cid = _cid(client)
    _upload(client, cid, "w3.txt", "WEEK THREE material", week="Week 3")
    fake(("# Week 3 notes\n", "max_tokens"))
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
