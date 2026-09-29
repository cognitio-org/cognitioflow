"""Today's plan, worked out from the exam dates. Computed on request and never stored: a stored plan can be wrong.

Decided by Matej on 2026-09-29: three hours a day; until the first exam (Property Law, 21 Oct) it takes two
thirds and the other course one third; after it, the remaining course takes the whole day.
"""
import re
from datetime import date

DAILY_MINUTES = 180
LEAD_SHARE = 2 / 3
SCRAP_CHARS = 1500   # a saved chat reply ("I need to stop you here.") is short; every real note measured 4,000+

_WEEK = re.compile(r"(?i)\b(?:week|wk|working\s+group|wg)\s*0?(\d{1,2})\b")


def shares(today: date, exams: dict) -> dict:
    """Each course's share of today. The nearest exam leads; a course whose exam has passed gets nothing."""
    active = sorted((d, c) for c, d in exams.items() if d and d >= today)
    out = {c: 0.0 for c in exams}
    if len(active) == 1:
        out[active[0][1]] = 1.0
    elif active:
        out[active[0][1]] = LEAD_SHARE
        for _, c in active[1:]:
            out[c] = (1 - LEAD_SHARE) / (len(active) - 1)
    return out


def week_of(title: str):
    m = _WEEK.search(title or "")
    return int(m.group(1)) if m else None


def sort_notes(notes: list) -> dict:
    """Notes by week, the course-wide reference notes, and the scraps (saved chat replies) kept out of sight."""
    out = {"weeks": {}, "reference": [], "scraps": []}
    for n in notes:
        if (n.get("chars") or 0) < SCRAP_CHARS:
            out["scraps"].append(n)
        elif week_of(n.get("title")) is not None:
            out["weeks"].setdefault(week_of(n["title"]), []).append(n)
        else:
            out["reference"].append(n)
    return out


def focus_week(today: date, weeks: list, due_by_week: dict):
    """The week with most cards due; with none due, the weeks take turns day by day so every week comes round."""
    if not weeks:
        return None
    if any(due_by_week.get(w, 0) for w in weeks):
        return max(sorted(weeks), key=lambda w: due_by_week.get(w, 0))
    ordered = sorted(weeks)
    return ordered[today.toordinal() % len(ordered)]


def tasks(minutes: int, due: int) -> list:
    """Read the week's notes, drill it with the tutor, clear the due cards (about a minute a card, at most 30%)."""
    if minutes <= 0:
        return []
    recall = min(round(minutes * 0.3), due)
    tutor = round(minutes * 0.3)
    out = [{"kind": "notes", "minutes": minutes - recall - tutor}, {"kind": "tutor", "minutes": tutor}]
    if recall:
        out.append({"kind": "recall", "minutes": recall, "cards": due})
    return out
