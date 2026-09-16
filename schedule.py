"""
Card scheduling seam (Phase 10).

  next_review(card, rating, now) -> {due, interval, stability, difficulty, state, step, last_review, ease, reps}

SCHEDULER=fsrs (default) asks FSRS, which learns from this card's own history; SCHEDULER=sm2 keeps the app's original
SM-2 arithmetic byte for byte. Ratings are the app's 0–3 (Again, Hard, Good, Easy) either way, and the SM-2 columns are
always kept up to date so switching back loses nothing.
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
