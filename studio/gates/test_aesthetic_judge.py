"""Self-contained tests for aesthetic_judge — no pytest, no real VLM/image."""

import os
import sys

# Ensure sibling import works regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aesthetic_judge import judge_aesthetics


def test_high_score_passes():
    vlm = lambda _p: '{"score": 0.82, "notes": "clean, high-contrast, juicy"}'
    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is True, v
    assert v.score == 0.82
    assert v.notes == "clean, high-contrast, juicy"


def test_low_score_fails():
    vlm = lambda _p: '{"score": 0.31, "notes": "flat, no feedback"}'
    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is False, v
    assert v.score == 0.31


def test_garbage_fails_closed():
    vlm = lambda _p: "Great game! I'd score it 95/100."
    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is False, v
    assert v.score == 0.0
    assert v.raw  # raw is always preserved


def test_fenced_json_is_parsed():
    vlm = lambda _p: '```json\n{"score": 0.7, "notes": "ok"}\n```'
    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is True, v
    assert v.score == 0.7


def test_out_of_range_fails_no_clamp():
    vlm = lambda _p: '{"score": 1.4, "notes": "hallucinated"}'
    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is False, v
    assert v.score == 0.0  # not clamped to 1.0


def test_bool_score_rejected():
    vlm = lambda _p: '{"score": true, "notes": "x"}'
    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is False, v


def test_vlm_raising_fails_closed():
    def vlm(_p):
        raise RuntimeError("model unreachable")

    v = judge_aesthetics("ignored.png", vlm)
    assert v.ok is False, v
    assert v.score == 0.0
    assert "model unreachable" in v.notes


if __name__ == "__main__":
    test_high_score_passes()
    test_low_score_fails()
    test_garbage_fails_closed()
    test_fenced_json_is_parsed()
    test_out_of_range_fails_no_clamp()
    test_bool_score_rejected()
    test_vlm_raising_fails_closed()
    print("OK")
