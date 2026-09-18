"""Paths that failed without telling anyone.

An audit drove each of these in Chromium against a stubbed 500 and measured what the page showed.
The answer, in every case here, was nothing. These assert against static/index.html the way
test_courses.py's palette test does, because there is no JS test runner and CLAUDE.md forbids one.
"""
import re
from pathlib import Path

PAGE = (lambda s: s("index.html") + s("app.js") + s("app.css") + s("book.css"))(
    lambda n: (Path(__file__).resolve().parent.parent / "static" / n).read_text(encoding="utf-8"))


def test_a_failed_autosave_says_so_and_offers_a_way_back():
    """The worst of them. scheduleSave awaited put() with no catch, so a rejected save left
    #noteStatus reading '…' for the rest of the session — no toast, nothing. A dropped connection
    during a lecture lost the capture while the screen still said everything was fine."""
    fn = re.search(r"async function saveNote\(\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "catch" in fn, "the save must not be able to fail silently"
    assert "dataset.state='failed'" in fn.replace(" ", "")
    assert "Retry" in fn, "a failure the user cannot act on is only half-reported"
    assert "#noteStatus[data-state=\"failed\"]" in PAGE, "and it has to look like a failure"


def test_the_reassuring_ellipsis_does_not_paper_over_a_live_failure():
    """Every keystroke re-armed the timer and reset the status to '…'. With the failure showing,
    that would flick back to something reassuring on the next character typed."""
    at = PAGE.index("function scheduleSave(){")
    fn = PAGE[at:PAGE.index("$('#noteTitle').addEventListener", at)]
    assert "dataset.state!=='failed'" in fn.replace(" ", ""), (
        "scheduleSave must leave a visible failure visible while it retries")


def test_actions_that_save_first_stop_when_the_save_fails():
    """Reconcile reads the note back from the server, and to-file snapshots it. Both did a bare
    `await put(...)` first, so a failed save meant acting on stale text — or an unhandled throw."""
    for btn in ("#noteReconcile", "#noteToTutor"):
        handler = re.search(re.escape(f"$('{btn}').onclick=") + r".*?\n(?=\$\(|function |/\*|let |const )",
                            PAGE, re.S).group(0)
        assert "await saveNote()" in handler, f"{btn} must go through the checked save"
        assert "return" in handler, f"{btn} must bail out when the save failed"


def test_a_toast_can_be_told_its_tone_rather_than_guessed_at():
    """Tone was inferred by regex from the wording. Measured failures that showed the SUCCESS dot:
    'The bench did not respond', 'Microphone blocked', and 'Mic: not-allowed' — the last because the
    pattern wanted 'not allowed' and the Speech API emits 'not-allowed'."""
    fn = re.search(r"function toast\(.*?\n[^\n]*setTimeout[^\n]*\}", PAGE, re.S).group(0)
    assert re.search(r"function toast\(m,\s*tone\)", fn), "callers must be able to state the tone"
    assert "tone||" in fn.replace(" ", ""), "the regex stays as the default so no existing call changes"
    assert "not[ -]allowed" in fn, "the hyphen the Speech API actually emits"
    for failure in ("The bench did not respond", "Microphone blocked", "'Mic: '+e.error"):
        line = next(l for l in PAGE.splitlines() if failure in l and "toast(" in l)
        assert "'warn')" in line, f"still shows as a success: {failure}"


def test_a_failed_grade_gives_the_submission_back():
    """courtReply cleared #courtType before the request, so a 502 lost a long answer outright and
    the only way forward was to say the whole thing again."""
    fn = re.search(r"async function courtReply\(text\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "$('#courtType').value=text" in fn, "the submission must come back on failure"
