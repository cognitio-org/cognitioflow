"""Coverage map w4: a repeatable build (pitch: 20 fresh Rebuilds on the demo course give one map).

The model only says which stated objectives each syllabus week serves and which authorities it turns on; topic names
and notes come from the course's own syllabus, the % from the weeks. Same inputs -> same saved map (input hash on the
saved map), temperature 0, one automatic retry. Pure: no database, no network; the model is a fake callable.
"""
import json

import pytest

import blueprint as bp
import course_brief as cb
import llm

WEEKS = [
    {"week": "1", "title": "Free movement of goods: the scope of Art 34 TFEU", "topics": ["Dassonville formula", "Mutual recognition"], "readings": ["Art 34 TFEU"]},
    {"week": "2", "title": "Establishment and services", "topics": ["The Gebhard test"], "readings": []},
    {"week": "3", "title": "Competition law: Art 102 TFEU", "topics": ["Dominance", "Abuse"], "readings": []},
]
BRIEF = {"syllabus": {"weeks": WEEKS, "source": "Demo schedule"},
         "learning_objectives": "Analyse the fundamental freedoms\nAnalyse EU competition law"}
SYL = cb.syllabus_block(BRIEF)
REPLY = {"weeks": [
    {"week": 1, "lo": [1], "law": ["Art 34 TFEU", "Dassonville"]},
    {"week": 2, "lo": [1], "law": ["Art 49 TFEU", "Gebhard", "Gebhard test", "golden shares", "Commission v Portugal (golden shares)"]},
    {"week": 3, "lo": [2, 9], "law": ["Art 102 TFEU", "United Brands"]},
    {"week": 30, "lo": [1], "law": ["Invented"]},
]}


def _norm(reply):
    return bp.normalise_blueprint(reply, syllabus_weeks=[1, 2, 3], objectives=["a", "b"],
                                  week_info=bp.weeks_from_block(SYL))


def test_weeks_from_block_reads_the_course_titles_and_topics():
    info = bp.weeks_from_block(SYL)
    assert info[1] == {"title": "Free movement of goods: the scope of Art 34 TFEU",
                       "topics": ["Dassonville formula", "Mutual recognition"]}
    assert info[2]["topics"] == ["The Gebhard test"] and info[3]["title"] == "Competition law: Art 102 TFEU"


def test_a_per_week_reply_becomes_topics_in_the_course_words():
    b = _norm(REPLY)
    names = [t["topic"] for t in b["topics"]]
    assert names == ["Free movement of goods: the scope of Art 34 TFEU", "Establishment and services",
                     "Competition law: Art 102 TFEU"]                       # week order, week 30 dropped
    t = {x["topic"]: x for x in b["topics"]}
    comp = t["Competition law: Art 102 TFEU"]
    assert comp["objectives"] == [2]                                       # objective 9 does not exist
    assert comp["note"] == "Covers Dominance; Abuse."                      # the syllabus, never a model note
    assert all(x["weight"] == 33 and x["share"] == 1 and x["share_of"] == 3 for x in b["topics"])
    assert b["weeks_total"] == 3 and b["objectives_total"] == 2 and b["objectives_mapped"] == [1, 2]


def test_doctrine_chips_are_deduplicated_and_capitalised():
    est = {x["topic"]: x for x in _norm(REPLY)["topics"]}["Establishment and services"]
    assert est["doctrines"] == ["Art 49 TFEU", "Gebhard test", "Commission v Portugal (golden shares)"]
    assert bp._tidy_doctrines(["golden shares"]) == ["Golden shares"]
    assert bp._tidy_doctrines(["Art 34 TFEU", "Art 34 TFEU and Art 36 TFEU"]) == ["Art 34 TFEU and Art 36 TFEU"]


def test_a_week_the_reply_leaves_out_or_misspells_is_still_a_topic():
    b = _norm({"weeks": [{"week": 1, "lo": [1], "law": ["Art 34 TFEU"]},
                         {"week": 3, "objectrines": [2], "law": ["Art 102 TFEU"]}]})   # a real model typo
    t = {x["topic"]: x for x in b["topics"]}
    assert set(t) == {"Free movement of goods: the scope of Art 34 TFEU", "Establishment and services",
                      "Competition law: Art 102 TFEU"}
    assert t["Establishment and services"]["doctrines"] == [] and t["Competition law: Art 102 TFEU"]["objectives"] == []


def test_an_objectives_only_course_maps_one_topic_per_objective():
    b = bp.normalise_blueprint({"objectives": [{"lo": 2, "law": ["Art 101 TFEU"]}, {"lo": 1, "law": ["Art 34 TFEU"]},
                                               {"lo": 7, "law": ["x"]}]},
                               syllabus_weeks=[], objectives=["Analyse the freedoms", "Analyse competition law"])
    assert [t["topic"] for t in b["topics"]] == ["Analyse the freedoms", "Analyse competition law"]
    assert b["basis"] == "objectives" and all(t["weight"] == 50 for t in b["topics"])


def test_a_volunteered_weight_on_a_fresh_build_is_never_called_a_legacy_estimate():
    b = bp.normalise_blueprint({"topics": [{"topic": "A", "weight": 60}, {"topic": "B", "weight": 40}]},
                               syllabus_weeks=[1, 2], objectives=[])
    assert b["basis"] == "none" and all(t["weight"] == 0 and t["confidence"] == "low" for t in b["topics"])
    legacy = bp.normalise_blueprint({"topics": [{"topic": "A", "weight": 60}, {"topic": "B", "weight": 40}]})
    assert legacy["basis"] == "model"                                      # a re-save of an old map keeps its weights


def test_same_reply_gives_a_byte_identical_map():
    outs = {json.dumps(_norm(json.loads(json.dumps(REPLY))), sort_keys=True) for _ in range(20)}
    assert len(outs) == 1


def test_input_hash_covers_rules_model_and_context(monkeypatch):
    h = bp.input_hash("gemini-2.5-flash", "ctx")
    assert h == bp.input_hash("gemini-2.5-flash", "ctx") and len(h) == 32
    assert h != bp.input_hash("other-model", "ctx") and h != bp.input_hash("gemini-2.5-flash", "ctx2")
    monkeypatch.setattr(bp, "RULES", bp.RULES + " changed")
    assert h != bp.input_hash("gemini-2.5-flash", "ctx")


def test_propose_returns_the_saved_map_for_the_same_inputs_without_a_model_call():
    calls = []
    first = bp.propose(SYL, lambda ctx: (calls.append(ctx) or REPLY), model="m")
    assert len(calls) == 1 and first["cached"] == "" and first["attempts"] == 1
    saved = bp.normalise_blueprint(first)                                  # what a Save stores (hash kept)
    assert saved["input_hash"] == first["input_hash"]
    again = bp.propose(SYL, lambda ctx: (calls.append(ctx) or REPLY), model="m", saved=saved)
    assert len(calls) == 1 and again["cached"] == "saved"
    assert [t["topic"] for t in again["topics"]] == [t["topic"] for t in first["topics"]]
    fresh = bp.propose(SYL, lambda ctx: (calls.append(ctx) or REPLY), model="m", saved=saved, fresh=True)
    assert len(calls) == 2 and fresh["cached"] == ""                       # the proof runs bypass the cache
    other = bp.propose(SYL, lambda ctx: (calls.append(ctx) or REPLY), model="other", saved=saved)
    assert len(calls) == 3 and other["cached"] == ""                       # a different model is a different input


class _Err(Exception):
    def __init__(self, status_code):
        super().__init__(status_code)
        self.status_code = status_code


def test_propose_retries_once_on_a_502_or_timeout_then_succeeds():
    seen = []

    def ask(ctx):
        seen.append(1)
        if len(seen) == 1:
            raise _Err(502)
        return REPLY
    b = bp.propose(SYL, ask, model="m", sleep=lambda s: None)
    assert len(seen) == 2 and b["attempts"] == 2 and len(b["topics"]) == 3

    seen.clear()
    with pytest.raises(TimeoutError):
        bp.propose(SYL, lambda ctx: (seen.append(1), (_ for _ in ()).throw(TimeoutError()))[1], model="m",
                   sleep=lambda s: None)
    assert len(seen) == 2                                                  # one retry, then the error goes up


def test_propose_does_not_retry_a_refusal():
    seen = []

    def ask(ctx):
        seen.append(1)
        raise _Err(403)
    with pytest.raises(_Err):
        bp.propose(SYL, ask, model="m", sleep=lambda s: None)
    assert len(seen) == 1


def test_propose_checks_the_reply_on_every_attempt():
    """A retry normalises again with the course scope passed explicitly (the build_context ContextVar is one-shot)."""
    seen = []

    def ask(ctx):
        seen.append(1)
        if len(seen) == 1:
            raise bp.BlueprintError("not a map")
        return REPLY
    b = bp.propose(SYL, ask, model="m", sleep=lambda s: None)
    assert [t["weeks"] for t in b["topics"]] == [[1], [2], [3]] and b["weeks_total"] == 3


def test_repeatable_kwargs_send_seed_and_no_reasoning_only_on_kernal(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", "anthropic")
    assert llm.repeatable_kwargs() == {"temperature": 0}
    monkeypatch.setattr(llm, "PROVIDER", "kernal")
    kw = llm.repeatable_kwargs()
    assert kw == {"temperature": 0, "seed": llm.REPEATABLE_SEED, "reasoning_effort": "disable"}
    body = llm._kernal_body("gemini-2.5-flash", "sys", [{"role": "user", "content": "x"}], 100, 0, False,
                            {"seed": 7, "reasoning_effort": "disable"})
    assert body["temperature"] == 0.0 and body["seed"] == 7 and body["reasoning_effort"] == "disable"


def test_the_tutor_block_names_every_week_of_a_twelve_week_map():
    """A per-week map has 12 topics; the old cap of 10 dropped weeks 11-12 (all of objective 6) from the tutor prompt."""
    weeks = [{"week": str(n), "title": f"Week title {n}", "topics": [f"T{n}"], "readings": []} for n in range(1, 13)]
    syl = cb.syllabus_block({"syllabus": {"weeks": weeks}})
    b = bp.normalise_blueprint({"weeks": [{"week": n, "lo": [], "law": [f"Case {n}"]} for n in range(1, 13)]},
                               syllabus_weeks=list(range(1, 13)), objectives=[], week_info=bp.weeks_from_block(syl))
    block = bp.blueprint_block({"blueprint": b})
    assert all(f"Week title {n}" in block for n in range(1, 13))
