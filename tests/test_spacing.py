"""spacing: review dates worked back from the real exam dates of semester 1a 2026. Pure, no database."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spacing  # noqa: E402

TODAY, PROPERTY, EU = date(2026, 9, 23), date(2026, 10, 21), date(2026, 11, 4)


def test_the_gap_is_fifteen_percent_of_what_is_left():
    assert spacing.days_left(TODAY, PROPERTY) == 28 and spacing.gap_days(TODAY, PROPERTY) == 4
    assert spacing.gap_days(PROPERTY, PROPERTY) == 0 and spacing.gap_days(date(2026, 10, 20), PROPERTY) == 1
    with pytest.raises(ValueError):
        spacing.gap_days(TODAY, PROPERTY, fraction=0.9)


def test_reviews_close_in_on_the_exam_and_end_the_day_before():
    r = spacing.review_dates(TODAY, PROPERTY)
    assert r[0] > TODAY and r[-1] == date(2026, 10, 20) and all(a < b for a, b in zip(r, r[1:]))
    gaps = [(b - a).days for a, b in zip(r, r[1:])]
    assert gaps == sorted(gaps, reverse=True)
    assert len(spacing.review_dates(TODAY, EU)) >= len(r) and spacing.review_dates(PROPERTY, PROPERTY) == []
