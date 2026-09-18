"""The >= 32px tap target CLAUDE.md asks for.

Measured in Chromium across all nine screens before the change: 59 distinct interactive elements
under 32px, the bulk of them .btn.small at 25.8px, with a 13x13 file checkbox — the control that
decides what the tutor reads — and an 18x18 session tick. After: 4, every one of them either an
input wrapped in a 32px label or an element whose hit area is a pseudo-element, which
getBoundingClientRect does not see.
"""
import re
from pathlib import Path

# The page was split on 2026-09-18: CSS moved to static/app.css and static/book.css,
# JS to static/app.js. These tests assert against all of it, so read the pieces and
# join them — that keeps the assertions honest wherever the code physically lives.
_STATIC = Path(__file__).resolve().parent.parent / "static"
def _read(name):
    p = _STATIC / name
    return p.read_text(encoding="utf-8") if p.exists() else ""
PAGE = _read("index.html") + chr(10) + _read("app.js")
CSS = re.sub(r"/\*.*?\*/", "", _read("app.css") + chr(10) + _read("book.css"), flags=re.S)


def _rule(sel):
    m = re.search(re.escape(sel) + r"\{([^}]*)\}", CSS)
    assert m, f"{sel} is gone — has it been renamed?"
    return m.group(1)


def test_the_floor_is_one_number():
    """Repeating 32px in eight places is how it drifts to 30 in one of them."""
    assert "--tap:32px" in CSS
    assert CSS.count("var(--tap)") >= 6


def test_the_small_button_meets_the_floor():
    """25.8px, and about forty of the fifty-nine were this one rule. It needs a width floor too —
    the planner's x button cleared the height and was still 27.2px wide."""
    r = _rule(".btn.small")
    assert "min-height:var(--tap)" in r and "min-width:var(--tap)" in r
    assert "inline-flex" in r, "padding alone will not raise a button whose line-box is shorter"


def test_the_smallest_control_in_the_app_meets_it_too():
    """#focusBtn measured 45.7 x 18.9. It keeps its quiet look: the padding grows, not the type."""
    r = _rule("#focusBtn")
    assert "min-height:var(--tap)" in r
    assert "font-size:.74rem" in r, "it should still read as a quiet chip, not a button"


def test_a_checkbox_is_hit_through_its_label():
    """An <input> cannot carry a pseudo-element, so the label is the target — which is what a label
    is for. Verified in Chromium: clicking 12px above the box's centre toggles it."""
    r = _rule(".tick")
    assert "min-height:var(--tap)" in r and "min-width:var(--tap)" in r
    assert re.search(r'<label class="tick"><input type="checkbox"', PAGE), \
        "the label must wrap the input, not sit beside it"
    # data-toggle stays on the input, or the change handler stops firing
    assert 'data-toggle="${f.id}"' in PAGE


def test_the_session_tick_grows_its_target_without_growing_itself():
    """18x18, and it is the control that marks a planned session done. The book tabs already use a
    padded pseudo-element for exactly this; the square stays 18px. Verified with elementFromPoint:
    a point 12px above the tick's centre resolves to the tick."""
    assert ".sess .chk::before" in CSS
    r = _rule(".sess .chk::before")
    assert "width:var(--tap)" in r and "height:var(--tap)" in r
    assert "position:absolute" in r
    assert "position:relative" in _rule(".sess .chk"), "the pseudo-element needs a positioned parent"
