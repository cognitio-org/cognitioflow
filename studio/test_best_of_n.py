"""Tests for studio/best_of_n.py (model-quality plan rung 2). Run: python3 studio/test_best_of_n.py. Synthetic only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import best_of_n  # noqa: E402

DET = best_of_n.DETERMINISTIC_GATES


def card(fail=(), doctrine=True, bad_items=0, overall=None, polish=False, drop=()):
    gates = [{"name": n, "passed": n not in fail} for n in DET + ("doctrine",) if n not in drop]
    for g in gates:
        if g["name"] == "doctrine":
            g["passed"] = doctrine
    gates.append({"name": "polish", "passed": polish})
    ok = (not fail) and doctrine is True and not drop
    return {"gates": gates, "enforced": list(DET) + ["doctrine"],
            "overall_pass": ok if overall is None else overall,
            "doctrine_items": [{"ok": True}] * 3 + [{"ok": False}] * bad_items}


def c(i, crd, g=0.5, r=0.5):
    return {"id": i, "card": crd, "grounding": g, "generation_ratio": r}


def test_none_pass_surfaces_nothing_with_reasons():
    out = best_of_n.select([c("a", card(fail=("retrieval",))), c("b", card(doctrine=False))])
    assert out["winner"] is None and out["ranked"] == []
    assert "retrieval" in out["reasons"]["a"] and "doctrine" in out["reasons"]["b"]
    assert best_of_n.select([])["winner"] is None


def test_only_the_all_gates_draft_wins():
    out = best_of_n.select([c("a", card(fail=("terminology",)), g=1.0), c("b", card(), g=0.1)])
    assert out["winner"] == "b" and out["reasons"]["b"] == "selected"


def test_ties_break_on_doctrine_then_grounding_then_ratio_then_id():
    assert best_of_n.select([c("a", card(), g=0.5), c("b", card(), g=0.9)])["winner"] == "b"
    assert best_of_n.select([c("a", card(), g=0.5, r=0.4), c("b", card(), g=0.5, r=0.8)])["winner"] == "b"
    assert best_of_n.select([c("b", card()), c("a", card())])["ranked"] == ["a", "b"]
    # fewer failing doctrine items beats better grounding (doctrine is the primary score)
    out = best_of_n.select([c("a", card(bad_items=0, overall=True), g=0.1),
                            c("b", card(bad_items=2, overall=True), g=1.0)])
    assert out["ranked"] == ["a", "b"]


def test_string_true_and_missing_gates_fail_closed():
    crd = card()
    crd["gates"][0]["passed"] = "true"
    assert not best_of_n.deterministic_pass(crd)
    assert not best_of_n.deterministic_pass(card(drop=("citations",)))
    assert best_of_n.select([c("a", card(overall="true"))])["winner"] is None
    assert best_of_n.select([c("a", "not a card"), c("b", None)])["winner"] is None


def test_polish_never_selects():
    assert best_of_n.select([c("a", card(polish=False))])["winner"] == "a"
    a, b = c("a", card(polish=True), g=0.1), c("b", card(polish=False), g=0.9)
    assert best_of_n.select([a, b])["winner"] == "b"


def test_nan_and_garbage_scores_do_not_crash():
    assert best_of_n.select([c("a", card(), g=float("nan")), c("b", card(), g="x")])["winner"] == "a"


def test_yield():
    assert best_of_n.yield_ok([{"winner": "a"}, {"winner": None}]) == 0.5 and best_of_n.yield_ok([]) == 0.0
    assert best_of_n.DEFAULT_N == 4


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  {t.__name__}: PASS")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  {t.__name__}: FAIL — {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
