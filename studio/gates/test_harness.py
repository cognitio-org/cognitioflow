import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import harness
from harness import GameSubmission, Runtime, run_gates, render, run_gate, build_card


class GoodPage:
    def console_errors(self):
        return []

    def query(self, selector):
        return True

    def title(self):
        return "The Docket"


class GoodA11y:
    def focus_visible(self):
        return True

    def reduced_motion_respected(self):
        return True

    def min_tap_target_px(self):
        return 44.0

    def min_contrast_ratio(self):
        return 7.0


def good_submission():
    return GameSubmission(
        game_meta={"title": "The Docket: Contract Formation"},
        source_text="A contract requires offer, acceptance, and consideration.",
        generated_text="Spot the issues: was there a valid offer, acceptance, and consideration?",
        game_spec={"interactions": [
            {"prompt": "State the rule for a valid offer", "answer": "..."},
            {"prompt": "Identify the consideration present", "answer": "..."},
            {"prompt": "Apply the acceptance rule to the facts", "answer": "..."},
            {"prompt": "State your conclusion with reasons", "answer": "..."},
        ]},
        required_selectors=["#board", "#submit"],
        screenshot_path="shot.png",
        bundle_text="<script>fetch('/api/catalogue/docket').then(r => r.json())</script>",
    )


def runtime(reviewer, vlm):
    return Runtime(reviewer=reviewer, vlm=vlm, page_probe=GoodPage(), a11y_probe=GoodA11y())


OK_REVIEWER = lambda prompt: '{"ok": true, "issues": []}'
OK_VLM = lambda path: '{"score": 0.82, "notes": "clean, readable"}'


def test_run_gate():
    """S2: public run_gate is the same fail-closed path run_gates uses."""
    assert harness.run_gate is harness._result  # alias, not a drifting copy

    ok = run_gate("terminology", True, lambda: (True, "clean"))
    assert ok == {"name": "terminology", "passed": True, "mandatory": True, "detail": "clean"}, ok
    assert run_gate("polish", False, lambda: (True, "ok"))["mandatory"] is False
    assert run_gate("x", True, lambda: (False, "bad"))["passed"] is False

    # only the literal True passes; truthy non-bools and None fail closed
    for v in ("true", 1, 1.0, {"ok": 1}, [True], None):
        r = run_gate("x", True, lambda v=v: (v, "d"))
        assert r["passed"] is False, (v, r)

    # non-2-tuple returns and raising gates fail closed, never crash run_gate
    def boom():
        raise RuntimeError("probe died")
    for fn in (lambda: True, lambda: None, lambda: (True,), lambda: (True, "a", "b"), boom):
        r = run_gate("x", True, fn)
        assert r["passed"] is False and r["detail"].startswith("gate error (fail-closed)"), r
    assert "probe died" in run_gate("x", True, boom)["detail"]

    # a detail whose str() raises fails closed too (Phase-1 _result raised here)
    class BadStr:
        def __str__(self):
            raise ValueError("unprintable")
    r = run_gate("x", True, lambda: (True, BadStr()))
    assert r["passed"] is False and "unprintable" in r["detail"], r

    # run_gates still goes through it: a raising reviewer is a blocking doctrine failure
    def down(p):
        raise RuntimeError("model unreachable")
    card = run_gates(good_submission(), runtime(down, OK_VLM))
    doc = next(g for g in card["gates"] if g["name"] == "doctrine")
    assert doc["passed"] is False and "model unreachable" in doc["detail"], doc


def test_build_card():
    """S2: build_card = build_review_card + extra metadata that can never change the verdict."""
    meta = {"title": "The Docket: Week 3", "course": "pil"}
    passing = [run_gate("terminology", True, lambda: (True, "ok")),
               run_gate("polish", False, lambda: (False, "cramped"))]
    failing = passing + [run_gate("doctrine", True, lambda: (False, "invented a defence"))]

    # extra=None -> exactly the review_card card
    from review_card import build_review_card
    assert build_card(meta, passing) == build_review_card(meta, passing)
    assert build_card(meta, failing, None) == build_review_card(meta, failing)

    # extra metadata is merged
    extra = {"mode": "shadow", "engine_hash": "abc123", "timings_ms": {"doctrine": 41000},
             "game_sha256": "f" * 64, "lexicon_version": "fallback", "infra_error": False}
    card = build_card(meta, passing, extra)
    assert card["overall_pass"] is True and card["blocking_failures"] == [], card
    for k, v in extra.items():
        assert card[k] == v, (k, card)

    # extra can NEVER flip a failing card, nor overwrite game/gates
    forged = {"overall_pass": True, "blocking_failures": [], "gates": [], "game": {"title": "x"},
              "mode": "enforce"}
    card = build_card(meta, failing, forged)
    assert card["overall_pass"] is False, card
    assert card["blocking_failures"] == ["doctrine"], card
    assert [g["name"] for g in card["gates"]] == ["terminology", "polish", "doctrine"], card
    assert card["game"] == meta and card["mode"] == "enforce", card

    # hand-built results are normalised fail-closed: only literal True passes,
    # and a missing/non-False `mandatory` counts as mandatory
    for bad in ("true", 1, None):
        card = build_card(meta, [{"name": "doctrine", "passed": bad, "mandatory": True, "detail": ""}])
        assert card["overall_pass"] is False and card["blocking_failures"] == ["doctrine"], (bad, card)
    card = build_card(meta, [{"name": "doctrine", "passed": False, "detail": ""}])
    assert card["overall_pass"] is False and card["gates"][0]["mandatory"] is True, card
    card = build_card(meta, [{"name": "doctrine", "passed": False, "mandatory": "no", "detail": ""}])
    assert card["overall_pass"] is False, card

    # inputs are not mutated
    hand = [{"name": "doctrine", "passed": "true", "detail": ""}]
    meta_copy, hand_copy, forged_copy = dict(meta), [dict(hand[0])], dict(forged)
    card = build_card(meta, hand, forged)
    card["game"]["title"] = "changed"
    card["gates"][0]["detail"] = "changed"
    assert meta == meta_copy and hand == hand_copy and forged == forged_copy, (meta, hand, forged)

    # renders like any other card
    md = render(build_card(meta, failing, extra))
    assert "Week 3" in md and "doctrine" in md


def main():
    # (a) everything passes -> overall pass, no blockers
    card = run_gates(good_submission(), runtime(OK_REVIEWER, OK_VLM))
    assert card["overall_pass"] is True, card
    assert card["blocking_failures"] == [], card

    # (b) doctrine fails (mandatory) -> blocks
    bad_doc = lambda p: '{"ok": false, "issues": ["invented a defence not in the source"]}'
    card = run_gates(good_submission(), runtime(bad_doc, OK_VLM))
    assert card["overall_pass"] is False
    assert "doctrine" in card["blocking_failures"], card

    # (c) polish low (advisory) -> does NOT block
    ugly = lambda path: '{"score": 0.1, "notes": "cramped, low contrast"}'
    card = run_gates(good_submission(), runtime(OK_REVIEWER, ugly))
    assert card["overall_pass"] is True, card
    polish = next(g for g in card["gates"] if g["name"] == "polish")
    assert polish["passed"] is False and polish["mandatory"] is False

    # (d) reviewer raises -> harness fails that gate closed, not a silent pass
    def boom(p):
        raise RuntimeError("model unreachable")
    card = run_gates(good_submission(), runtime(boom, OK_VLM))
    assert card["overall_pass"] is False and "doctrine" in card["blocking_failures"]

    # (e) calls an external AI at play-time -> self_contained blocks
    sub = good_submission()
    sub.bundle_text = "<script>fetch('https://api.anthropic.com/v1/messages')</script>"
    card = run_gates(sub, runtime(OK_REVIEWER, OK_VLM))
    assert card["overall_pass"] is False and "self_contained" in card["blocking_failures"], card

    # render smoke
    md = render(card)
    assert "The Docket" in md and "❌" in md

    test_run_gate()
    test_build_card()

    print("OK")


main()
