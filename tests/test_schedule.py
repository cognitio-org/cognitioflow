"""Phase 10: card scheduling. SM-2 stays exactly as it was; FSRS schedules from the card's own history."""
from datetime import date, datetime, timedelta, timezone

import pytest

import schedule

NEW = {"ease": 2.5, "interval": 0, "reps": 0}


def sm2(monkeypatch):
    monkeypatch.setattr(schedule, "BACKEND", "sm2")


def fsrs_or_skip(monkeypatch):
    monkeypatch.setattr(schedule, "BACKEND", "fsrs")
    if not schedule.available():
        pytest.skip("fsrs is not installed")


def test_sm2_is_unchanged(monkeypatch):
    sm2(monkeypatch)
    first = schedule.next_review(dict(NEW), 2)                       # Good on a new card: 1 day
    assert (first["interval"], first["reps"]) == (1, 1)
    assert first["due"] == (date.today() + timedelta(days=1)).isoformat()
    second = schedule.next_review({"ease": 2.5, "interval": 1, "reps": 1}, 2)   # then 6 days
    assert second["interval"] == 6
    again = schedule.next_review({"ease": 2.5, "interval": 6, "reps": 2}, 0)    # Again resets
    assert (again["interval"], again["reps"]) == (0, 0) and again["ease"] < 2.5


def test_fsrs_keeps_the_sm2_columns_so_switching_back_loses_nothing(monkeypatch):
    fsrs_or_skip(monkeypatch)
    out = schedule.next_review(dict(NEW), 2)
    assert out["reps"] == 1 and out["ease"] > 0 and out["due"]
    assert out["stability"] > 0 and 1 <= out["difficulty"] <= 10 and out["state"] in (1, 2, 3)


def test_fsrs_gives_a_harder_card_a_sooner_return_than_an_easy_one(monkeypatch):
    fsrs_or_skip(monkeypatch)
    card = dict(NEW)
    hard = schedule.next_review(dict(card), 1)
    easy = schedule.next_review(dict(card), 3)
    assert easy["due"] >= hard["due"]
    assert easy["interval"] >= hard["interval"]


def test_fsrs_stretches_the_interval_as_a_card_matures(monkeypatch):
    fsrs_or_skip(monkeypatch)
    now = datetime.now(timezone.utc)
    card = dict(NEW)
    intervals = []
    for _ in range(5):                                   # five "Good" reviews, each a month after the last
        out = schedule.next_review(card, 2, now)
        intervals.append(out["interval"])
        card = {**card, **{k: out.get(k) for k in ("stability", "difficulty", "state", "step", "last_review", "ease", "reps", "interval")}}
        now += timedelta(days=30)
        card["last_review"] = now.timestamp()
    assert intervals[-1] > intervals[0], intervals       # later reviews are spaced further apart


def test_a_missing_library_falls_back_to_sm2_rather_than_failing_a_review(monkeypatch):
    monkeypatch.setattr(schedule, "BACKEND", "fsrs")
    monkeypatch.setattr(schedule, "available", lambda: False)
    out = schedule.next_review(dict(NEW), 2)
    assert out["interval"] == 1 and "stability" not in out
