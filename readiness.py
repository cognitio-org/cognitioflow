"""Exam-readiness scoring, per examined doctrine (built by the swarm, reviewed by Claude).

Pure stdlib logic, deterministic, no network. Measures EXAM-READINESS — card retention and
IRAC-drill success on a doctrine — not study time. run.py maps a course's examined blueprint
topics onto Doctrine signals and calls these; the Progress screen renders the result.
"""
from dataclasses import dataclass


@dataclass
class Doctrine:
    key: str
    cards_total: int = 0
    cards_due: int = 0
    drills_attempted: int = 0
    drills_passed: int = 0


def _validate(d: Doctrine) -> None:
    numeric_fields = (
        d.cards_total,
        d.cards_due,
        d.drills_attempted,
        d.drills_passed,
    )
    if any(value < 0 for value in numeric_fields):
        raise ValueError("All numeric fields must be non-negative")
    if d.drills_passed > d.drills_attempted:
        raise ValueError("drills_passed cannot exceed drills_attempted")


def retention(d: Doctrine) -> float:
    """1.0 when there is nothing to forget; otherwise the share of cards not currently due."""
    _validate(d)
    if d.cards_total == 0:
        return 1.0
    return max(0.0, min(1.0, 1 - d.cards_due / d.cards_total))


def drill_rate(d: Doctrine) -> float:
    """0.0 when the doctrine has never been drilled (unproven); otherwise the pass rate."""
    _validate(d)
    if d.drills_attempted == 0:
        return 0.0
    return max(0.0, min(1.0, d.drills_passed / d.drills_attempted))


def score(d: Doctrine) -> float:
    return round(0.5 * retention(d) + 0.5 * drill_rate(d), 3)


def status(d: Doctrine) -> str:
    doctrine_score = score(d)
    if doctrine_score >= 0.8:
        return "ready"
    if doctrine_score >= 0.5:
        return "shaky"
    return "weak"


def overall(doctrines: list[Doctrine]) -> dict:
    if not doctrines:
        return {
            "mean_score": 0.0,
            "by_status": {"ready": 0, "shaky": 0, "weak": 0},
            "weakest": [],
        }

    scores = [score(doctrine) for doctrine in doctrines]
    by_status = {"ready": 0, "shaky": 0, "weak": 0}
    for doctrine in doctrines:
        by_status[status(doctrine)] += 1

    weakest = sorted(doctrines, key=lambda doctrine: (score(doctrine), doctrine.key))[:3]

    return {
        "mean_score": round(sum(scores) / len(scores), 3),
        "by_status": by_status,
        "weakest": [doctrine.key for doctrine in weakest],
    }
