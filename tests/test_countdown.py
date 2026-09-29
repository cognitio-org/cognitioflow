"""countdown: today's share of the two exams, notes by week, the focus week, the day's tasks. Pure, no database."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import countdown as cd  # noqa: E402
from pytest import approx  # noqa: E402

PROP, EU = date(2026, 10, 21), date(2026, 11, 4)


def test_property_leads_with_two_thirds_until_its_exam_then_eu_takes_the_day():
    assert cd.shares(date(2026, 9, 29), {"prop": PROP, "eu": EU}) == approx({"prop": 2 / 3, "eu": 1 / 3})
    assert cd.shares(date(2026, 10, 22), {"prop": PROP, "eu": EU}) == {"prop": 0.0, "eu": 1.0}
    assert cd.shares(date(2026, 11, 5), {"prop": PROP, "eu": EU}) == {"prop": 0.0, "eu": 0.0}
    assert cd.shares(date(2026, 9, 29), {"prop": PROP, "x": None})["x"] == 0.0


def test_notes_sort_into_weeks_reference_and_scraps():
    notes = [{"id": 1, "title": "Week 3 — Transfer of goods", "chars": 10377},
             {"id": 2, "title": "WEEK 2 EU LAW COMPLETE LECTURE NOTES", "chars": 7089},
             {"id": 3, "title": "WORKING GROUP 2 — CASE 2", "chars": 7622},
             {"id": 4, "title": "The method — how every answer is built", "chars": 11496},
             {"id": 5, "title": "I need to stop you here.", "chars": 1156}]
    s = cd.sort_notes(notes)
    assert [n["id"] for n in s["weeks"][3]] == [1] and [n["id"] for n in s["weeks"][2]] == [2, 3]
    assert [n["id"] for n in s["reference"]] == [4] and [n["id"] for n in s["scraps"]] == [5]


def test_the_week_with_most_due_cards_is_the_focus_and_otherwise_weeks_take_turns():
    assert cd.focus_week(date(2026, 9, 29), [1, 2, 3], {2: 5, 3: 9}) == 3
    days = {cd.focus_week(date(2026, 9, d), [1, 2, 3], {}) for d in (1, 2, 3)}
    assert days == {1, 2, 3} and cd.focus_week(date(2026, 9, 29), [], {}) is None


def test_the_day_is_notes_tutor_and_the_due_cards():
    t = cd.tasks(120, due=8)
    assert [x["kind"] for x in t] == ["notes", "tutor", "recall"] and sum(x["minutes"] for x in t) == 120
    assert t[2] == {"kind": "recall", "minutes": 8, "cards": 8}
    assert [x["kind"] for x in cd.tasks(60, due=0)] == ["notes", "tutor"] and cd.tasks(0, 5) == []
