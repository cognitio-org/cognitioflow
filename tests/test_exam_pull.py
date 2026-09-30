"""The exam run-in (approved 2026-09-30, "95%"): in a course's last 14 days, cards FSRS expects him to recall below
95% on exam day come forward, weakest first, under a daily cap. Exam dates are semester 1a's real ones."""
from datetime import date, datetime, timedelta, timezone

import pytest
from fsrs import Scheduler

import run
import schedule

PROP, EU = date(2026, 10, 21), date(2026, 11, 4)


@pytest.fixture(autouse=True)
def no_fuzz(monkeypatch):
    """FSRS adds random fuzz to intervals; the run-in is judged on the same deck every time."""
    monkeypatch.setattr(schedule, "_scheduler", Scheduler(enable_fuzzing=False))


def _rating(i, n):   # a fixed mix: 10% Again, 20% Hard, 50% Good, 20% Easy
    k = (i * 7 + n * 3) % 10
    return 0 if k == 0 else 1 if k < 3 else 3 if k > 7 else 2


def _run(n, exam, days, sweep=True, start=date(2026, 9, 30)):
    """Rate every due card each day to the exam, sweeping first. Returns per-day reviews, cards, and the plans."""
    cards = [{"id": f"c{i}", "due": start.isoformat()} for i in range(n)]
    seen, per, plans = [0] * n, [], []
    for d in range(days):
        today = start + timedelta(days=d)
        if sweep:
            plan = schedule.plan_exam_pull(cards, today, exam)
            plans.append((today, plan))
            for kid, day in plan.items():
                cards[int(kid[1:])]["due"] = day.isoformat()
        count = 0
        for i, c in enumerate(cards):
            if c["due"] <= today.isoformat():
                c.update(schedule.next_review(c, _rating(i, seen[i]), datetime(today.year, today.month, today.day, 9, tzinfo=timezone.utc)))
                seen[i] += 1; count += 1
        per.append(count)
    return per, cards, plans


@pytest.mark.parametrize("n,exam,days", [(137, PROP, 21), (160, EU, 35)])
def test_every_card_reaches_95_percent_on_exam_day(n, exam, days):
    _, before, _ = _run(n, exam, days, sweep=False)
    _, after, _ = _run(n, exam, days)
    r95 = lambda cs: sum((schedule.recall_on(c, exam) or 0) >= schedule.EXAM_RECALL for c in cs)
    assert r95(after) == n > r95(before)


@pytest.mark.parametrize("n,exam,days", [(137, PROP, 21), (160, EU, 35)])
def test_the_cap_holds_and_nothing_lands_on_or_after_the_exam(n, exam, days):
    _, _, plans = _run(n, exam, days)
    assert any(p for _, p in plans)
    for today, plan in plans:
        assert all(today <= d < exam for d in plan.values())
        per_day = {}
        for d in plan.values(): per_day[d] = per_day.get(d, 0) + 1
        assert all(v <= schedule.EXAM_DAILY_CAP for v in per_day.values())
        assert per_day.get(exam - timedelta(days=1), 0) <= schedule.EXAM_DAILY_CAP // 2


def test_no_eve_pile_up():
    per, _, _ = _run(137, PROP, 21)
    assert per[-1] <= schedule.EXAM_DAILY_CAP and max(per[4:]) <= 60   # after the first days' backlog, no day explodes


def test_weakest_first_when_the_cap_bites():
    now = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)
    cards = [{"id": f"w{i}", "due": "2026-10-30", "stability": 5 + i, "difficulty": 5.0, "last_review": now.timestamp()} for i in range(60)]
    plan = schedule.plan_exam_pull(cards, date(2026, 10, 19), PROP, cap=10)   # two days left, eve holds half: 15 fit
    assert len(plan) == 15 and set(plan) == {f"w{i}" for i in range(15)}


def test_outside_the_window_or_without_an_exam_nothing_moves():
    now = datetime(2026, 9, 30, 9, tzinfo=timezone.utc)
    cards = [{"id": "a", "due": "2026-10-25", "stability": 3.0, "difficulty": 5.0, "last_review": now.timestamp()}]
    assert schedule.plan_exam_pull(cards, date(2026, 10, 6), PROP) == {}      # 15 days out
    assert schedule.plan_exam_pull(cards, date(2026, 10, 7), PROP) != {}      # 14 days out
    assert schedule.plan_exam_pull(cards, date(2026, 10, 10), None) == {}
    assert schedule.plan_exam_pull(cards, PROP, PROP) == {}


def test_a_course_without_an_exam_date_is_untouched(client, pg, monkeypatch):
    cid = client.post("/api/courses", json={"name": "No Exam Law"}).json()["id"]
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "f", "back": "b"}).json()["id"]
    pg.execute("UPDATE cards SET due='2026-12-01', stability=2, difficulty=5, last_review=%s WHERE id=%s", (datetime.now(timezone.utc).timestamp(), kid)); pg.commit()
    client.get(f"/api/courses/{cid}/cards"); client.get("/api/today")
    assert pg.execute("SELECT due FROM cards WHERE id=%s", (kid,)).fetchone()[0] == "2026-12-01"


def test_the_sweep_brings_a_weak_card_forward_through_the_api(client, pg, monkeypatch):
    today = run._local_today()
    cid = client.post("/api/courses", json={"name": "Run-in Law"}).json()["id"]
    pg.execute("UPDATE courses SET exam_date=%s WHERE id=%s", ((today + timedelta(days=10)).isoformat(), cid))
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "f", "back": "b"}).json()["id"]
    late = (today + timedelta(days=30)).isoformat()
    pg.execute("UPDATE cards SET due=%s, stability=3, difficulty=6, last_review=%s WHERE id=%s", (late, datetime.now(timezone.utc).timestamp(), kid)); pg.commit()
    run._SWEPT.clear()
    client.get("/api/today")
    due = pg.execute("SELECT due FROM cards WHERE id=%s", (kid,)).fetchone()[0]
    assert today.isoformat() <= due < (today + timedelta(days=10)).isoformat()
