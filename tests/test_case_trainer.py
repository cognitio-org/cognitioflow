"""Phase 20: the exam-hypothetical case trainer. Mirrors the essay/oral bank tests — a bank built from
the student's own ticked files, served one at a time, graded through the app's one review path."""
import io
import json
import types

import pytest

import casetrainer


# ---------------------------------------------------------------- the pure module (no DB, no model)
def test_length_falls_back_to_short():
    assert casetrainer.length_of("full") == "full"
    assert casetrainer.length_of("SHORT") == "short"
    assert casetrainer.length_of("essay") == "short"   # an unknown value is the safe default, never an error
    assert casetrainer.length_of(None) == "short"


def test_a_malformed_mcq_is_dropped_not_shown():
    good = {"question": "Which provision?", "options": ["Art 34", "Art 45", "Art 56", "Art 110"],
            "correct_index": 0, "explanation": "Art 34 governs MEQRs."}
    assert casetrainer.valid_mcq(good)
    # correct_index out of range would mark every answer wrong; fewer/non-distinct options leave <4 choices.
    assert not casetrainer.valid_mcq({**good, "correct_index": 9})
    assert not casetrainer.valid_mcq({**good, "options": ["Art 34", "Art 45", "Art 56"]})
    assert not casetrainer.valid_mcq({**good, "options": ["Art 34", "Art 34", "Art 56", "Art 110"]})
    assert not casetrainer.valid_mcq({**good, "question": "   "})


def test_normalise_case_keeps_only_usable_mcqs_and_needs_facts():
    raw = {"facts": "A rule bans imports.", "mcqs": [
        {"question": "Q1", "options": ["a", "b", "c", "d"], "correct_index": 1, "explanation": "because"},
        {"question": "Q2", "options": ["a", "b"], "correct_index": 0},   # malformed → dropped
    ]}
    c = casetrainer.normalise_case(raw)
    assert c and len(c["mcqs"]) == 1 and c["mcqs"][0]["question"] == "Q1"
    assert casetrainer.normalise_case({"facts": "", "mcqs": [raw["mcqs"][0]]}) is None   # no facts
    assert casetrainer.normalise_case({"facts": "x", "mcqs": []}) is None                 # no usable MCQ


def test_choose_rotates_least_recently_seen_first():
    cases = [{"id": "a", "seen": 100.0, "created": 1}, {"id": "b", "seen": None, "created": 2},
             {"id": "c", "seen": 50.0, "created": 3}]
    assert casetrainer.choose(cases)["id"] == "b"   # never seen wins
    assert casetrainer.choose([cases[0], cases[2]])["id"] == "c"   # then the oldest
    assert casetrainer.choose([]) is None


def test_rating_maps_a_miss_to_again_and_a_hit_to_good():
    assert casetrainer.rating_for(False) == 0   # Again — what you missed comes back
    assert casetrainer.rating_for(True) == 2    # Good — never 'Easy', which is not inferred


# ---------------------------------------------------------------- model-backed routes (fake client)
class FakeClient:
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


def _cid(client):
    return client.get("/api/courses").json()[0]["id"]


def _upload(client, cid, name, text, week=""):
    return client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(text.encode()), "text/plain")}, data={"week": week}).json()["id"]


# A source long enough to clear CASE_MIN_SOURCE_CHARS, so the grounding test is not also a thin-source test.
SOURCE = (("Art 34 TFEU prohibits measures having equivalent effect to quantitative restrictions on imports. "
           "Dassonville defines an MEQR as all trading rules capable of hindering intra-Union trade. "
           "Cassis de Dijon adds the rule of reason and mandatory requirements. ") * 4)

CASE_REPLY = json.dumps([{
    "facts": "A Dutch rule requires all imported liquorice to carry a Dutch-language label. Bram, an importer, challenges it.",
    "thin": False,
    "mcqs": [
        {"concept": "Free movement of goods", "question": "Which Treaty provision governs the labelling rule?",
         "options": ["Art 34 TFEU", "Art 45 TFEU", "Art 56 TFEU", "Art 110 TFEU"], "correct_index": 0,
         "explanation": "Art 34 TFEU governs MEQRs on imports; Dassonville catches the labelling rule."},
        {"concept": "MEQR test", "question": "Which case defines an MEQR?",
         "options": ["Dassonville", "Keck", "Cassis de Dijon", "Bosman"], "correct_index": 0,
         "explanation": "Dassonville: all trading rules capable of hindering intra-Union trade."},
    ],
}])


def _bank(client, cid, fake, length="short", week="", source=SOURCE):
    _upload(client, cid, "w2.txt", source, week=week)
    fake((CASE_REPLY, None))
    return client.post(f"/api/courses/{cid}/case/bank", json={"count": 1, "length": length, "week": week}).json()


def test_bank_is_grounded_in_ticked_files_only_on_the_cheap_tier(client, fake, pg):
    import run
    cid = _cid(client)
    _upload(client, cid, "w2.txt", SOURCE, week="2")
    off = _upload(client, cid, "not-ticked.txt", "Zambrano and the Ruiz Zambrano citizenship line", week="2")
    assert client.post(f"/api/files/{off}/toggle-to", json={"on": False}).status_code == 200
    fc = fake((CASE_REPLY, None))
    r = client.post(f"/api/courses/{cid}/case/bank", json={"count": 1, "length": "short", "week": "2"}).json()
    assert r["made"] == 1 and r["mcqs"] == 2

    sent = fc.calls[0]["messages"][0]["content"]
    assert "Dassonville" in sent and "Zambrano" not in sent, "an un-ticked file reached the writer"
    assert "[OUTSIDE FILES]" in sent, "the label the course uses for anything beyond the ticked files"
    assert run.DISTRACTOR_GUIDANCE in sent, "the wrong options must use the quiz's student-error guidance"
    assert fc.calls[0]["model"] == run.CHEAP_MODEL, "banking is not the analytical call"
    assert fc.calls[0]["model"] != run.STRONG_MODEL
    assert fc.calls[0]["system"] == run.CASE_GROUNDING_RULES

    banked = pg.execute("SELECT course_id, week, length FROM case_hypos").fetchall()
    assert banked == [(cid, "2", "short")]
    mcqs = pg.execute("SELECT count(*) FROM case_hypo_mcqs WHERE course_id=%s", (cid,)).fetchone()[0]
    assert mcqs == 2


def test_both_lengths_are_selectable_and_stored(client, fake, pg):
    cid = _cid(client)
    _bank(client, cid, fake, length="full")
    assert pg.execute("SELECT length FROM case_hypos").fetchone()[0] == "full"
    # /next can be narrowed to a length that exists, and returns nothing for one that does not.
    assert client.post(f"/api/courses/{cid}/case/next", json={"length": "full"}).json()["case"] is not None
    assert client.post(f"/api/courses/{cid}/case/next", json={"length": "short"}).json()["case"] is None


def test_next_serves_the_case_without_answers(client, fake):
    cid = _cid(client)
    _bank(client, cid, fake)
    d = client.post(f"/api/courses/{cid}/case/next", json={}).json()
    assert d["left"] == 1 and d["case"]["facts"].startswith("A Dutch rule")
    q = d["case"]["mcqs"][0]
    assert q["id"] and len(q["options"]) == 4
    assert "correct_index" not in q and "explanation" not in json.dumps(d), "the answer travelled with the question"


def test_a_miss_schedules_a_card_and_a_hit_schedules_nothing(client, fake, pg):
    cid = _cid(client)
    _bank(client, cid, fake)
    d = client.post(f"/api/courses/{cid}/case/next", json={}).json()
    q0, q1 = d["case"]["mcqs"][0], d["case"]["mcqs"][1]

    # A wrong answer: immediate corrective feedback, and the gap becomes a card due through the review path.
    miss = client.post(f"/api/courses/{cid}/case/answer", json={"qid": q0["id"], "selected_index": 1}).json()
    assert miss["correct"] is False and miss["correct_index"] == 0
    assert "Dassonville" in miss["explanation"] and miss["due"]
    row = pg.execute("SELECT front, back, source FROM cards WHERE course_id=%s", (cid,)).fetchall()
    assert len(row) == 1 and row[0][0] == q0["question"] and row[0][2].startswith("case:")
    assert pg.execute("SELECT count(*) FROM reviews").fetchone()[0] == 1   # the one review path logged it

    # A correct answer on another MCQ with no card behind it schedules nothing.
    hit = client.post(f"/api/courses/{cid}/case/answer", json={"qid": q1["id"], "selected_index": 0}).json()
    assert hit["correct"] is True and hit["due"] is None
    assert pg.execute("SELECT count(*) FROM cards WHERE course_id=%s", (cid,)).fetchone()[0] == 1   # still just the miss


def test_answering_the_same_mcq_right_later_rates_the_same_card_not_a_second(client, fake, pg):
    cid = _cid(client)
    _bank(client, cid, fake)
    q0 = client.post(f"/api/courses/{cid}/case/next", json={}).json()["case"]["mcqs"][0]
    client.post(f"/api/courses/{cid}/case/answer", json={"qid": q0["id"], "selected_index": 1})   # miss → card
    client.post(f"/api/courses/{cid}/case/answer", json={"qid": q0["id"], "selected_index": 0})   # later: right
    assert pg.execute("SELECT count(*) FROM cards WHERE course_id=%s", (cid,)).fetchone()[0] == 1   # one card per MCQ
    assert pg.execute("SELECT count(*) FROM reviews").fetchone()[0] == 2                            # both ratings logged


def test_empty_source_is_400_before_any_model_call(client, fake):
    cid = _cid(client)
    fake()   # any model call would raise
    r = client.post(f"/api/courses/{cid}/case/bank", json={"count": 1})
    assert r.status_code == 400


def test_abstains_on_a_thin_source(client, fake):
    import run
    cid = _cid(client)
    _upload(client, cid, "tiny.txt", "Art 34 TFEU.")   # well under CASE_MIN_SOURCE_CHARS
    fc = fake((json.dumps([]), None))                   # the writer abstains: no case supported
    r = client.post(f"/api/courses/{cid}/case/bank", json={"count": 1}).json()
    assert r["made"] == 0 and r["thin"] is True
    assert "too thin" in fc.calls[0]["messages"][0]["content"].lower(), "the thin source is flagged to the writer"


def test_a_non_json_reply_is_502(client, fake):
    cid = _cid(client)
    _upload(client, cid, "w2.txt", SOURCE)
    fake(("Sorry, I can't do that.", None))
    assert client.post(f"/api/courses/{cid}/case/bank", json={"count": 1}).status_code == 502


def test_bank_cannot_read_a_file_from_another_course(client, fake):
    cid = _cid(client)
    other = client.post("/api/courses", json={"name": "Property"}).json()["id"]
    secret = _upload(client, other, "secret.txt", "Property law: numerus clausus of property rights")
    fake()   # a cross-course read would send its text to the model and raise here
    r = client.post(f"/api/courses/{cid}/case/bank", json={"count": 1, "file_id": secret})
    assert r.status_code == 404
