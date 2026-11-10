"""Studio adapter part 1 (S3): the pure projections from a finished docket game to gate inputs.
Wrong options are wrong on purpose: their text/story must never reach terminology or doctrine pass 1."""
import copy

import docketgen
from studio import docket_adapter as da
from test_docketgen import game
from test_produce_interactions import produce_game


def keyed():
    return docketgen.source_keys([
        {"id": "f1", "name": "Week 3 lecture.pdf", "role": "lecture", "text": "A contract made under duress is void."},
        {"id": "f2", "name": "WG notes.pdf", "role": "wg", "text": "State liability needs a sufficiently serious breach."},
    ])


def mcq_game():
    g = game()
    for s in g["scenes"]:
        for o in (s.get("quiz") or {}).get("options") or []:
            o["story"] = f"story {o['key']}"
    return g


def by_id(items):
    return {i["id"]: i for i in items}


def test_cited_source_text_dedupes_skips_unknown_and_caps():
    k = keyed()
    text = da.cited_source_text(["S1", "[S1 p.4]", "S9", "S2"], k)
    assert text.count("[S1] Week 3 lecture.pdf") == 1 and "[S2] WG notes.pdf" in text
    assert "void" in text and "sufficiently serious" in text and "S9" not in text
    assert da.cited_source_text([], k) == "" and da.cited_source_text(["S9"], k) == ""
    big = docketgen.source_keys([{"name": "a.pdf", "text": "A" * 20_000}, {"name": "b.pdf", "text": "B" * 20_000}])
    capped = da.cited_source_text(["S1", "S2"], big)
    assert len(capped) <= da.SOURCE_CAP and "[S2] b.pdf" in capped and "B" * 100 in capped


def test_terminology_items_exclude_wrong_options_text_and_story():
    items = by_id(da.items_for_terminology(mcq_game(), keyed()))
    assert list(items) == ["q2", "q3", "verdict"]
    q2 = items["q2"]
    assert q2["kind"] == "mcq" and q2["cites"] == ["S1"]
    assert "answer B" in q2["generated_text"]
    for wrong in ("answer A", "answer C", "answer D", "story A", "story C", "story D"):
        assert wrong not in q2["generated_text"]
    for k in "ABCD":
        assert f"because [S1] {k}" in q2["generated_text"]          # every option's teaching is checked
    assert "duress is void" in q2["source_text"] and "sufficiently serious" not in q2["source_text"]
    assert items["verdict"]["generated_text"] == "r [S1]" and items["verdict"]["cites"] == ["S1"]


def test_doctrine_rounds_carry_question_correct_answer_and_all_teaching():
    items = by_id(da.rounds_for_doctrine(mcq_game(), keyed()))
    assert list(items) == ["q2", "q3", "verdict"]
    gen = items["q3"]["generated_text"]
    assert "QUESTION: Advise her." in gen and "CORRECT ANSWER: answer B" in gen
    assert all(f"because [S1] {k}" in gen for k in "ABCD")
    assert not any(w in gen for w in ("answer A", "answer C", "answer D", "story A", "story C"))
    assert "IRAC RULE: r [S1]" in items["verdict"]["generated_text"]


def test_distractors_are_every_wrong_option_and_only_those():
    items = da.distractors_for_review(mcq_game(), keyed())
    assert [i["id"] for i in items] == ["q2:A", "q2:C", "q2:D", "q3:A", "q3:C", "q3:D"]
    a = items[0]
    assert a["round"] == "q2" and a["key"] == "A" and a["question"] == "Advise her."
    assert "OPTION: answer A" in a["generated_text"] and "STORY: story A" in a["generated_text"]
    assert "TEACHING: because [S1] A" in a["generated_text"] and "duress is void" in a["source_text"]
    assert not any("answer B" in i["generated_text"] for i in items)


def test_projections_work_on_the_finished_game_and_never_mutate_it():
    final = docketgen.finish(mcq_game(), "gabc", "CF-prop", keyed())
    before = copy.deepcopy(final)
    for fn in (da.items_for_terminology, da.rounds_for_doctrine, da.distractors_for_review):
        assert fn(final, keyed())
    assert final == before


def test_an_item_that_cites_nothing_is_checked_against_all_sources():
    g = mcq_game()
    for o in g["scenes"][1]["quiz"]["options"]:
        o["cites"], o["teaching"] = [], f"plain {o['key']}"
    q2 = by_id(da.items_for_terminology(g, keyed()))["q2"]
    assert q2["cites"] == [] and "[S1]" in q2["source_text"] and "[S2]" in q2["source_text"]


def test_produce_kinds_project_only_the_answer_key():
    g = produce_game()
    g["scenes"][2]["quiz"]["answer"]["bank"].append({"id": "e9", "label": "Direct effect first"})   # bank distractor
    g["scenes"][3]["quiz"]["answer"]["elements"].append({"id": "e4", "label": "Unused element"})
    items = by_id(da.items_for_terminology(g, keyed()))
    assert list(items) == ["q1", "q2", "q3", "verdict"]
    spot = items["q1"]["generated_text"]
    assert "State liability" in spot and "Causal link" in spot and "Two issues" in spot
    assert "Proportionality" not in spot                                   # taxonomy distractor
    order = items["q2"]["generated_text"]
    assert "1. The rule confers rights" in order and "3. Causal link to the loss" in order
    assert "Direct effect first" not in order
    slot = items["q3"]["generated_text"]
    assert "The directive conferred an individual right -> Rights" in slot and "Unused element" not in slot
    assert items["q1"]["kind"] == "spot" and items["q1"]["cites"] == ["S1"]
    doc = by_id(da.rounds_for_doctrine(g, keyed()))
    assert "FACTS: The Member State failed to transpose" in doc["q1"]["generated_text"]
    assert "CORRECT ANSWER: 2. The breach is sufficiently serious" in doc["q2"]["generated_text"]
    assert "Proportionality" not in doc["q1"]["generated_text"]
    assert da.distractors_for_review(g, keyed()) == []


def test_malformed_games_project_to_nothing_instead_of_raising():
    for bad in ({}, {"scenes": None}, {"scenes": ["x", {"quiz": "nope"}]}, {"verdict": "x"}):
        assert da.items_for_terminology(bad, keyed()) == []
        assert da.rounds_for_doctrine(bad, keyed()) == []
        assert da.distractors_for_review(bad, keyed()) == []
