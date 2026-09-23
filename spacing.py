"""Review dates worked back from an exam date.

Cepeda et al. (2008): the best gap between reviews is roughly 10-20% of the time left until the test.
"""
from datetime import date, timedelta


def days_left(today: date, exam: date) -> int:
    return max(0, (exam - today).days)


def gap_days(today: date, exam: date, fraction: float = 0.15) -> int:
    if not 0.05 <= fraction <= 0.5:
        raise ValueError("fraction must be between 0.05 and 0.5")
    left = days_left(today, exam)
    return 0 if left == 0 else max(1, round(left * fraction))


def review_dates(first_study: date, exam: date, fraction: float = 0.15) -> list[date]:
    """Strictly increasing dates before the exam, ending on the day before it."""
    out, d = [], first_study
    while (g := gap_days(d, exam, fraction)) and (d := d + timedelta(days=g)) < exam:
        out.append(d)
    eve = exam - timedelta(days=1)
    if eve > first_study and (not out or out[-1] != eve):
        out.append(eve)
    return out
