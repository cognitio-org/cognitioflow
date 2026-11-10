"""Self-contained tests for retrieval_density — no pytest required."""

import os
import sys

# Ensure sibling import works regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from retrieval_density import classify_interaction, is_retrieval, score_retrieval


def test_classify_mcq_recognition():
    """A 4-option MCQ should be classified as recognition."""
    interaction = {
        "kind": "mcq",
        "prompt": "What is 2+2?",
        "options": ["1", "2", "3", "4"],
        "answer": "4",
    }
    result = classify_interaction(interaction)
    assert result == "recognition", f"Expected 'recognition', got {result!r}"


def test_classify_free_text_generation():
    """Free-text recall (no options) should be classified as generation."""
    interaction = {
        "kind": "free-text",
        "prompt": "Name the capital of France.",
        "answer": "Paris",
    }
    result = classify_interaction(interaction)
    assert result == "generation", f"Expected 'generation', got {result!r}"


def test_recall_heavy_spec_passes():
    """Mostly free-text, no options → passes True, generation_ratio high."""
    # 8 free-text retrieval + 2 MCQ retrieval = 10 interactions
    interactions = []
    for i in range(8):
        interactions.append({
            "kind": "free-text",
            "prompt": f"Recall fact {i}",
            "answer": f"answer {i}",
        })
    for i in range(2):
        interactions.append({
            "kind": "mcq",
            "prompt": f"Pick answer {i}",
            "options": ["a", "b", "c"],
            "answer": "a",
        })
    spec = {"interactions": interactions}
    result = score_retrieval(spec)
    # n=10, n_retrieval=10, density=1.0
    assert result["n"] == 10
    assert result["n_retrieval"] == 10
    assert result["density"] == 1.0
    # generation_ratio = 8/10 = 0.8 (>=0.4)
    assert result["generation_ratio"] == 0.8, f"Expected 0.8, got {result['generation_ratio']}"
    assert result["passes"] is True, f"Expected passes=True, got {result}"


def test_all_mcq_spec_fails():
    """All-MCQ spec → passes False (generation_ratio 0.0)."""
    interactions = [
        {
            "kind": "mcq",
            "prompt": f"Question {i}",
            "options": ["a", "b", "c", "d"],
            "answer": "a",
        }
        for i in range(6)
    ]
    spec = {"interactions": interactions}
    result = score_retrieval(spec)
    # n=6, n_retrieval=6, density=1.0
    # generation_ratio = 0/6 = 0.0 (< 0.4)
    assert result["n"] == 6
    assert result["n_retrieval"] == 6
    assert result["density"] == 1.0
    assert result["generation_ratio"] == 0.0
    assert result["passes"] is False, f"Expected passes=False, got {result}"


def test_half_passive_reading_fails_density():
    """Half passive reading cards → density below floor → passes False."""
    interactions = []
    # 3 retrieval (free-text with answer)
    for i in range(3):
        interactions.append({
            "kind": "free-text",
            "prompt": f"Recall {i}",
            "answer": f"ans {i}",
        })
    # 7 passive reading (no answer, no options)
    for i in range(7):
        interactions.append({
            "kind": "info",
            "prompt": f"Read this fact {i}",
        })
    spec = {"interactions": interactions}
    result = score_retrieval(spec)
    # n=10, n_retrieval=3, density=0.3 (< 0.5)
    assert result["n"] == 10
    assert result["n_retrieval"] == 3
    assert result["density"] == 0.3, f"Expected 0.3, got {result['density']}"
    # generation_ratio = 3/3 = 1.0 (>=0.4) but density fails
    assert result["generation_ratio"] == 1.0
    assert result["passes"] is False, f"Expected passes=False, got {result}"


if __name__ == "__main__":
    test_classify_mcq_recognition()
    test_classify_free_text_generation()
    test_recall_heavy_spec_passes()
    test_all_mcq_spec_fails()
    test_half_passive_reading_fails_density()
    print("OK")
