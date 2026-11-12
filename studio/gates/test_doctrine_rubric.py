"""Doctrine-judge rubric (doctrine-judge-2): fail on legal substance, not wording. No pytest required.

Offline: the model is mocked. Each fixture in doctrine_rubric_fixtures.json carries the verdict a correct judge
gives ('mock'); these tests prove the gate turns that verdict into the expected pass/fail (quote rule included),
that both prompts carry the rubric, and that the new 'wording_notes' outlet never lets a failing verdict pass.
Whether the real Thinker follows the rubric is checked by doctrine_rubric_live.py on the M4, not here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

from studio.gates.doctrinal_review import (  # noqa: E402
    JUDGE_RUBRIC_VERSION, LEGAL_SUBSTANCE_RUBRIC, NO_REASON, build_distractor_prompt, build_prompt,
    parse_verdict, review_distractor, review_doctrine,
)

FIXTURES = json.load(open(os.path.join(os.path.dirname(__file__), "doctrine_rubric_fixtures.json")))["fixtures"]


def _by_id(fid):
    return next(f for f in FIXTURES if f["id"] == fid)


def _mock(verdict, seen=None):
    def reviewer(prompt):
        if seen is not None:
            seen.append(prompt)
        return json.dumps(verdict)
    return reviewer


def test_fixture_set_covers_the_cases():
    kinds = {f["kind"] for f in FIXTURES}
    assert {"wording", "term_of_art", "wrong_element"} <= kinds, kinds
    for f in FIXTURES:
        assert f["expect"] is (f["kind"] == "wording"), f["id"]
    print("  (a) fixtures: wording passes, term-of-art / wrong element / wrong actor fail: PASS")


def test_fixtures_through_the_gate_with_a_mocked_judge():
    for f in FIXTURES:
        seen = []
        v = review_doctrine(f["source"], f["generated"], _mock(f["mock"], seen), require_quotes=True)
        assert v.ok is f["expect"], (f["id"], v)
        assert f["source"] in seen[0] and f["generated"] in seen[0], f["id"]   # judged against the source text
    print("  (b) every fixture gets its expected verdict through review_doctrine: PASS")


def test_synonym_pass_with_source_quote_survives_quote_rule():
    """The generated text says 'in'/'take'; the quote is the SOURCE's own words ('within'/'adopt') and verifies."""
    for fid in ("synonym-in-within", "synonym-take-adopt"):
        f = _by_id(fid)
        v = review_doctrine(f["source"], f["generated"], _mock(f["mock"]), require_quotes=True)
        assert v.ok is True and v.issues == [], (fid, v)
    print("  (c) synonym rounds pass with verified source quotes: PASS")


def test_wording_notes_never_rescue_a_failure():
    f = _by_id("term-of-art-meqr")
    bad = dict(f["mock"], wording_notes=["only wording"])
    assert review_doctrine(f["source"], f["generated"], _mock(bad), require_quotes=True).ok is False
    # a wording remark put in "issues" next to ok:true is still contradictory: fails closed, as before
    f = _by_id("synonym-in-within")
    noisy = dict(f["mock"], issues=["'in' instead of 'within'"])
    assert review_doctrine(f["source"], f["generated"], _mock(noisy), require_quotes=True).ok is False
    # ok:true without quotes still fails the quote rule
    bare = {"ok": True, "issues": [], "wording_notes": ["x"]}
    assert review_doctrine(f["source"], f["generated"], _mock(bare), require_quotes=True).ok is False
    print("  (d) wording_notes cannot rescue a fail; issues+ok and unquoted ok still fail: PASS")


def test_wording_notes_shape_is_not_validated_against():
    """An odd wording_notes value is ignored, never a reason to pass or to crash."""
    v = parse_verdict(json.dumps({"ok": False, "issues": ["WRONG TEST: x"], "wording_notes": "not a list"}))
    assert v.ok is False and v.issues == ["WRONG TEST: x"]
    print("  (e) malformed wording_notes ignored: PASS")


def test_unexplained_failure_still_fails_and_says_so():
    v = parse_verdict('{"ok": false, "issues": []}')
    assert v.ok is False and v.issues == [NO_REASON], v
    v = parse_verdict('{"ok": false, "issues": ["MISSING CONDITION: y"]}')
    assert v.issues == ["MISSING CONDITION: y"]
    print("  (f) ok:false with no issues fails and is labelled: PASS")


def test_rubric_in_both_prompts():
    p1 = build_prompt("SRC", "GEN")
    p2 = build_distractor_prompt("SRC", "Q", "OPT", "TEACH")
    for p in (p1, p2):
        assert LEGAL_SUBSTANCE_RUBRIC in p
        assert '"wording_notes"' in p and "Quotes are the SOURCE's own words" in p
        assert "never set \"ok\" to false with an empty \"issues\" list" in p
    for must in ("MEANING of the SOURCE", "WRONG TEST", "WRONG OUTCOME", "MISSING CONDITION", "WRONG ACTOR",
                 "MISSTATED HOLDING", "TERM OF ART CHANGED",
                 "measures having equivalent effect", "similar measures", '"in" for "within"', '"take" for "adopt"'):
        assert must in LEGAL_SUBSTANCE_RUBRIC, must
    assert "DISTRACTOR" not in p1          # adapter tests tell pass 1 from pass 2 by this word
    assert "DISTRACTOR (the wrong option, including any story text):\nOPT\n\nTEACHING" in p2
    assert JUDGE_RUBRIC_VERSION == "doctrine-judge-2"
    print("  (g) rubric, wording_notes and paraphrase-quote rule in both prompts: PASS")


def test_distractor_pass_with_mocked_judge():
    src = _by_id("wrong-actor")["source"]
    ok = {"ok": True, "issues": [], "quotes": ["it may bring the matter before the Court of Justice"],
          "wording_notes": ["teaching says 'take the case to' for 'bring the matter before'"]}
    assert review_distractor(src, "Who may sue?", "OPTION: Any individual", "Only the Commission may.",
                             _mock(ok)).ok is True
    bad = {"ok": False, "issues": ["WRONG ACTOR: the teaching names the Council"], "quotes": []}
    assert review_distractor(src, "Who may sue?", "OPTION: Any individual", "Only the Council may.",
                             _mock(bad)).ok is False
    print("  (h) distractor pass: paraphrased teaching passes, wrong actor fails: PASS")


if __name__ == "__main__":
    test_fixture_set_covers_the_cases()
    test_fixtures_through_the_gate_with_a_mocked_judge()
    test_synonym_pass_with_source_quote_survives_quote_rule()
    test_wording_notes_never_rescue_a_failure()
    test_wording_notes_shape_is_not_validated_against()
    test_unexplained_failure_still_fails_and_says_so()
    test_rubric_in_both_prompts()
    test_distractor_pass_with_mocked_judge()
    print("OK")
