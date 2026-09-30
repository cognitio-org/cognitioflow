"""
Card scheduling seam (Phase 10).

  next_review(card, rating, now) -> {due, interval, stability, difficulty, state, step, last_review, ease, reps}

SCHEDULER=fsrs (default) asks FSRS, which learns from this card's own history; SCHEDULER=sm2 keeps the app's original
SM-2 arithmetic byte for byte. Ratings are the app's 0–3 (Again, Hard, Good, Easy) either way, and the SM-2 columns are
always kept up to date so switching back loses nothing.

plan_exam_pull is the exam run-in: in a course's last 14 days, the cards FSRS expects him to recall below 95% on
exam day come forward, weakest first, never more than a day's cap on any one day.
"""
import os
from datetime import date, datetime, timedelta, timezone

BACKEND = os.environ.get("SCHEDULER", "fsrs").strip().lower()
RATINGS = ("Again", "Hard", "Good", "Easy")
_scheduler = None


def _fsrs():
    global _scheduler
    if _scheduler is None:
        from fsrs import Scheduler
        _scheduler = Scheduler()
    return _scheduler


def available() -> bool:
    if BACKEND != "fsrs":
        return False
    try:
        _fsrs(); return True
    except Exception:
        return False


def _sm2(card: dict, rating: int) -> dict:
    """The original: 0 Again resets, otherwise 1 day, then 6, then interval × ease."""
    quality = [0, 3, 4, 5][max(0, min(3, rating))]
    ease, interval, reps = card.get("ease") or 2.5, card.get("interval") or 0, card.get("reps") or 0
    if quality < 3:
        reps, interval = 0, 0
    else:
        interval = 1 if reps == 0 else (6 if reps == 1 else round(interval * ease))
        reps += 1
    ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    return {"ease": ease, "interval": interval, "reps": reps,
            "due": (date.today() + timedelta(days=interval)).isoformat()}


def next_review(card: dict, rating: int, now: datetime = None) -> dict:
    """What this rating means for when the card comes back. Falls back to SM-2 if FSRS can't run."""
    out = _sm2(card, rating)                      # always maintained, so SCHEDULER=sm2 stays honest
    if not available():
        return out
    from fsrs import Card, Rating, State
    now = now or datetime.now(timezone.utc)
    stored = card.get("stability")
    fsrs_card = Card(
        state=State(card["state"]) if card.get("state") else State.Learning,
        step=card.get("step"),
        stability=stored, difficulty=card.get("difficulty"),
        due=datetime.fromtimestamp(card["last_review"], timezone.utc) if card.get("last_review") else now,
        last_review=datetime.fromtimestamp(card["last_review"], timezone.utc) if card.get("last_review") else None,
    )
    updated, _ = _fsrs().review_card(fsrs_card, Rating(max(1, min(4, rating + 1))), now)
    days = max(0, (updated.due - now).days)
    out.update({
        "due": updated.due.date().isoformat(),
        "interval": days,
        "stability": updated.stability,
        "difficulty": updated.difficulty,
        "state": int(updated.state),
        "step": updated.step,
        "last_review": now.timestamp(),
    })
    return out


# ---------------------------------------------------------------- exam run-in (approved by Matej 2026-09-30: "95%")
EXAM_WINDOW = 14       # days before the exam in which cards are pulled forward
EXAM_RECALL = 0.95     # the recall wanted on exam day; FSRS itself schedules for 0.90
EXAM_DAILY_CAP = 40    # cards due on any one day, counting what FSRS already put there (about 40 minutes)


def recall_on(card: dict, day: date):
    """FSRS's chance he still recalls this card on `day` (at 09:00 UTC), or None when it has no FSRS memory yet."""
    if not card.get("stability") or not card.get("last_review") or not available():
        return None
    from fsrs import Card, State
    c = Card(state=State.Review, stability=card["stability"], difficulty=card.get("difficulty"),
             last_review=datetime.fromtimestamp(card["last_review"], timezone.utc))
    return _fsrs().get_card_retrievability(c, datetime(day.year, day.month, day.day, 9, tzinfo=timezone.utc))


def plan_exam_pull(cards: list, today: date, exam, cap: int = EXAM_DAILY_CAP) -> dict:
    """{card id: new due date} for the cards to bring forward; empty outside the window or without an exam.

    A card qualifies when it is due on or after the exam and its recall there is below EXAM_RECALL. The weakest
    go first, each to the last day its recall is still at the target (or today, if it has already fallen below),
    stepping earlier - then later - past any day that is full (the eve holds half the cap). A card no day has room for keeps its date.
    Cards already due before the exam are never moved, and nothing goes on the exam day or after it.
    """
    if not exam or not (exam - timedelta(days=EXAM_WINDOW) <= today < exam):
        return {}
    last = exam - timedelta(days=1)
    days = [today + timedelta(days=i) for i in range((last - today).days + 1)]
    load = {d: 0 for d in days}
    wanted = []
    for c in cards:
        due = date.fromisoformat(str(c["due"])[:10]) if c.get("due") else today
        if due < exam:
            load[max(due, today)] += 1   # overdue cards are today's load
            continue
        r = recall_on(c, exam)
        if r is not None and r < EXAM_RECALL:
            wanted.append((r, str(c["id"]), c))
    moves = {}
    for _, kid, c in sorted(wanted):
        target = next((d for d in days if (recall_on(c, d + timedelta(days=1)) or 0) < EXAM_RECALL), last)
        i = days.index(target)
        for d in days[i::-1] + days[i + 1:]:
            if load[d] < (cap // 2 if d == last else cap):   # the eve is for the weakest few, not the whole deck
                load[d] += 1
                moves[kid] = d
                break
    return moves
