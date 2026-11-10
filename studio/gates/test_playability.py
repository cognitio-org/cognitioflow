"""Self-contained tests for playability — no pytest, no real browser."""

import os
import sys

# Ensure sibling import works regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playability import check_playability


class FakeProbe:
    """A browser-free PageProbe for the gate's core logic."""

    def __init__(self, errors=None, present=None, raises=False):
        self._errors = list(errors or [])
        # present: set of selectors that exist; None means "all present".
        self._present = present
        self._raises = raises

    def console_errors(self):
        if self._raises:
            raise RuntimeError("probe exploded")
        return list(self._errors)

    def query(self, selector):
        if self._present is None:
            return True
        return selector in self._present

    def title(self):
        return "Fake Game"


def test_clean_page_passes():
    probe = FakeProbe(errors=[], present=None)
    verdict = check_playability(probe, ["#board", "#submit"])
    assert verdict.ok is True, verdict
    assert verdict.errors == []
    assert verdict.missing_selectors == []


def test_console_error_fails():
    probe = FakeProbe(errors=["Uncaught ReferenceError: foo is not defined"])
    verdict = check_playability(probe, ["#board"])
    assert verdict.ok is False, verdict
    assert verdict.errors == ["Uncaught ReferenceError: foo is not defined"]
    assert verdict.missing_selectors == []


def test_missing_selector_fails_and_is_listed():
    probe = FakeProbe(errors=[], present={"#board"})
    verdict = check_playability(probe, ["#board", "#submit", "#score"])
    assert verdict.ok is False, verdict
    assert verdict.errors == []
    # Order of required_selectors is preserved.
    assert verdict.missing_selectors == ["#submit", "#score"]


def test_broken_probe_fails_closed():
    probe = FakeProbe(raises=True)
    verdict = check_playability(probe, ["#board"])
    assert verdict.ok is False, verdict
    assert any("probe failure" in e for e in verdict.errors), verdict


if __name__ == "__main__":
    test_clean_page_passes()
    test_console_error_fails()
    test_missing_selector_fails_and_is_listed()
    test_broken_probe_fails_closed()
    print("OK")
