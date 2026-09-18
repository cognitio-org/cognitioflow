"""The quality floor CLAUDE.md states: visible keyboard focus, prefers-reduced-motion respected,
and nothing irreversible happening without being asked.

Each of these was measured failing in Chromium before it was fixed. No JS test runner here, so they
assert against static/index.html the way test_courses.py's palette test does.
"""
import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "static"
_read = lambda name: (_STATIC / name).read_text(encoding="utf-8")

# index.html used to carry the markup, the script and the styles together. Splitting it into
# app.js/app.css/book.css left the <style> block empty of existence, so the search below returned
# None and this module failed at import. These assertions are about the page as the browser
# assembles it, so PAGE is the markup plus the script it loads, and CSS is both stylesheets.
PAGE = _read("index.html") + _read("app.js")
CSS = re.sub(r"/\*.*?\*/", "", _read("app.css") + _read("book.css"), flags=re.S)


def test_nothing_irreversible_happens_without_asking():
    """Two deletes were built inside innerHTML loops and missed the confirm() every other delete in
    the file has. The card carries its whole FSRS review history; one stray click in the All cards
    table threw away weeks of scheduling with nothing shown."""
    for hook, what in (("data-delcard", "a card and its review history"), ("data-delsess", "a planned session")):
        at = PAGE.index(f"document.querySelectorAll('[{hook}]')")
        handler = PAGE[at:PAGE.index("loadRecall()" if "card" in hook else "loadPlanner()", at) + 14]
        assert "confirm(" in handler, f"deleting {what} still asks nothing"
        assert "return" in handler, f"answering no to {what} must not delete it anyway"


def test_the_focused_delete_button_is_visible():
    """`.sess .act{opacity:0}` had only a :hover companion, so tabbing through the agenda landed on
    a fully transparent button that permanently deletes a session — with no focus ring to see,
    because the element itself was transparent. Measured: activeElement was the button, opacity 0."""
    rule = next(r for r in CSS.split("}") if ".sess" in r and ".act{opacity:1" in r + "}")
    assert ":focus-within" in rule, "a focused delete button must become visible, not only a hovered one"


def test_reduced_motion_reaches_the_flashcard():
    """A half-second 180-degree rotation through 1600px of perspective, on the screen used most and
    most repetitively. The reduce block near the top of the sheet could never win against it: the
    .fcinner declaration comes ~150 lines LATER at equal specificity. The override has to be last."""
    blocks = [m for m in re.finditer(r"@media\(prefers-reduced-motion:reduce\)\{", CSS)]
    assert blocks, "no reduce block at all"
    covering = [m for m in blocks if ".fcinner" in CSS[m.start():m.start() + 400]]
    assert covering, ".fcinner is not in any reduce block"
    fc_declared = CSS.index(".fcinner{position:relative")
    assert covering[-1].start() > fc_declared, (
        "the reduce block sits BEFORE the .fcinner declaration, so it loses the cascade at equal "
        "specificity — this is exactly how the original one silently covered only the book")


def test_the_command_palette_holds_focus_and_can_always_be_escaped():
    """#pal is role="dialog" over a dimmed page, but one Tab walked focus out to #focusBtn and the
    nav behind the dim, and Escape was bound on #palQ alone — so once focus left, the overlay was
    still up with no keyboard way out. The 3D player already does this correctly; reuse it."""
    assert "palBehind" in PAGE, "the page behind the dialog must be inert while it is open"
    opener = re.search(r"function openPal\(\)\{.*?\n\}", PAGE, re.S).group(0)
    closer = re.search(r"function closePal\(\)\{.*?\n  palOpener=null; \}", PAGE, re.S).group(0)
    assert "palBehind(true)" in opener and "palBehind(false)" in closer
    assert "palOpener" in closer, "focus must go back where it came from, not onto <body>"
    at = PAGE.index("document.addEventListener('keydown'", PAGE.index("function closePal"))
    doc = PAGE[at:PAGE.index("});", at)]      # the handler runs over two lines
    assert "Escape" in doc, "Escape must be handled at the document, not only on the input"
