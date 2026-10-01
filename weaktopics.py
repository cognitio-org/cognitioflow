"""Weak topics (Phase 18b): which syllabus weeks need work, from what he has actually done. Pure, no database.

A topic is a week of the syllabus. Its recall is the share of its last 20 card reviews he got (Hard, Good or Easy;
oral answers are graded into the same log), and its essay record is the method steps missed in the last two
marked drafts on it. Decided in the Phase 18 brief: a topic is weak when recall over the last 20 is below 80%, or
an essay missed a step in the last two drafts; with fewer than 5 reviews it is "not yet known", not weak.
Counts only - "11 of 20" - never a score out of 100 (Phase 17's rule).
"""
LAST = 20
MIN_REVIEWS = 5
WEAK_RECALL = 0.8
LAST_DRAFTS = 2


def rank(reviews: list, drafts: list, labels: dict = None) -> dict:
    """reviews: [(week, rating 0-3, created)]; drafts: [(week, criteria list, created)]; labels: {week: title}.

    Returns {"weak": [...], "holding": [...], "unknown": [...]}, weak ones weakest first. Each topic is
    {"week", "label", "reviews", "recalled", "missed"}: `reviews`/`recalled` count the last 20 at most, and
    `missed` names the steps missed in the last two marked drafts.
    """
    labels = labels or {}
    by_week, essays = {}, {}
    for week, rating, created in sorted(reviews, key=lambda r: r[2] or 0):
        by_week.setdefault(_w(week), []).append(rating)
    for week, criteria, created in sorted(drafts, key=lambda d: d[2] or 0):
        if isinstance(criteria, list) and criteria:
            essays.setdefault(_w(week), []).append(criteria)
    out = {"weak": [], "holding": [], "unknown": []}
    for week in sorted(set(by_week) | set(essays) | set(map(_w, labels)), key=_order):
        last = by_week.get(week, [])[-LAST:]
        recalled = sum(1 for r in last if (r or 0) >= 1)
        missed = []
        for criteria in essays.get(week, [])[-LAST_DRAFTS:]:
            for c in criteria:
                step = str(c.get("step") or "").strip() if isinstance(c, dict) else ""
                if step and c.get("met") is False and step not in missed:
                    missed.append(step)
        t = {"week": week, "label": labels.get(week) or (f"Week {week}" if week else "Cards without a week"),
             "reviews": len(last), "recalled": recalled, "missed": missed}
        if missed or (len(last) >= MIN_REVIEWS and recalled < WEAK_RECALL * len(last)):
            out["weak"].append(t)
        elif len(last) < MIN_REVIEWS:
            out["unknown"].append(t)
        else:
            out["holding"].append(t)
    out["weak"].sort(key=lambda t: (t["recalled"] / t["reviews"] if t["reviews"] else 1.0, -len(t["missed"]), _order(t["week"])))
    return out


def _w(week) -> str:
    return str(week or "").strip()


def _order(week: str):
    return (0, int(week), "") if week.isdigit() else (1, 0, week)
