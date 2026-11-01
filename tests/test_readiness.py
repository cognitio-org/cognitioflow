import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from readiness import Doctrine, drill_rate, overall, retention, score, status


@pytest.mark.parametrize(
    ("doctrine", "expected"),
    [
        (Doctrine("empty"), 1.0),
        (Doctrine("half-due", cards_total=10, cards_due=5), 0.5),
        (Doctrine("all-due", cards_total=10, cards_due=10), 0.0),
        (Doctrine("overdue", cards_total=10, cards_due=12), 0.0),
    ],
)
def test_retention(doctrine, expected):
    assert retention(doctrine) == expected


@pytest.mark.parametrize(
    ("doctrine", "expected"),
    [
        (Doctrine("unattempted"), 0.0),
        (Doctrine("partial", drills_attempted=4, drills_passed=3), 0.75),
        (Doctrine("none-passed", drills_attempted=4, drills_passed=0), 0.0),
    ],
)
def test_drill_rate(doctrine, expected):
    assert drill_rate(doctrine) == expected


def test_drill_rate_rejects_passed_greater_than_attempted():
    with pytest.raises(ValueError):
        drill_rate(Doctrine("invalid", drills_attempted=2, drills_passed=3))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cards_total", -1),
        ("cards_due", -1),
        ("drills_attempted", -1),
        ("drills_passed", -1),
    ],
)
def test_drill_rate_rejects_negative_numeric_fields(field, value):
    with pytest.raises(ValueError):
        drill_rate(Doctrine("invalid", **{field: value}))


def test_retention_rejects_negative_numeric_fields():
    with pytest.raises(ValueError):
        retention(Doctrine("invalid", cards_due=-1))


def test_score_uses_equal_weighting_and_rounds_to_three_decimals():
    doctrine = Doctrine(
        "weighted",
        cards_total=10,
        cards_due=2,
        drills_attempted=4,
        drills_passed=3,
    )
    assert retention(doctrine) == 0.8
    assert drill_rate(doctrine) == 0.75
    assert score(doctrine) == 0.775


@pytest.mark.parametrize(
    ("doctrine", "expected"),
    [
        (Doctrine("exactly-ready", cards_total=10, cards_due=4, drills_attempted=1, drills_passed=1), "ready"),
        (Doctrine("exactly-shaky"), "shaky"),
        (Doctrine("below-shaky", cards_total=10, cards_due=10), "weak"),
    ],
)
def test_status_thresholds(doctrine, expected):
    assert status(doctrine) == expected


def test_overall_mean_status_counts_and_weakest_ties():
    doctrines = [
        Doctrine("z-weak", cards_total=10, cards_due=10),                                    # score 0.0
        Doctrine("ready", cards_total=10, cards_due=2, drills_attempted=1, drills_passed=1),  # 0.5*0.8 + 0.5*1.0 = 0.9
        Doctrine("a-weak", cards_total=10, cards_due=10),                                    # score 0.0
        Doctrine("shaky"),                                                                   # 0.5*1.0 + 0.5*0.0 = 0.5
    ]

    assert overall(doctrines) == {
        "mean_score": 0.35,   # (0.0 + 0.9 + 0.0 + 0.5) / 4
        "by_status": {"ready": 1, "shaky": 1, "weak": 2},
        "weakest": ["a-weak", "z-weak", "shaky"],   # by (score, key): 0.0/a, 0.0/z, 0.5/shaky
    }


def test_overall_limits_weakest_to_three_doctrines():
    doctrines = [
        Doctrine("d", cards_total=10, cards_due=10),
        Doctrine("c", cards_total=10, cards_due=10),
        Doctrine("b", cards_total=10, cards_due=10),
        Doctrine("a", cards_total=10, cards_due=10),
    ]

    assert overall(doctrines)["weakest"] == ["a", "b", "c"]


def test_overall_empty_list():
    assert overall([]) == {
        "mean_score": 0.0,
        "by_status": {"ready": 0, "shaky": 0, "weak": 0},
        "weakest": [],
    }
