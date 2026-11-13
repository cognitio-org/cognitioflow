"""Guard the public landing page against overclaims that the code does not back up."""
from pathlib import Path

LANDING = (Path(__file__).resolve().parent.parent / "static" / "landing.html").read_text(encoding="utf-8")

REMOVED_OVERCLAIMS = [
    "never guesses",
    "Privacy-first",
    "IRAC throughout",
    "verified against your files",
    "Speech uses Google Cloud in the EU",
    "stays inside your syllabus",
    "getting harder exactly",
]


def test_removed_overclaims_absent():
    present = [p for p in REMOVED_OVERCLAIMS if p.lower() in LANDING.lower()]
    assert not present, f"overclaims back on the landing page: {present}"


def test_not_affiliated_line_present():
    assert "not affiliated with or endorsed by the University of Groningen" in LANDING


def test_citation_check_scope_stated():
    assert "Cases cited by name only, and national-law citations, are not checked." in LANDING
    assert "found in your selected sources" not in LANDING
