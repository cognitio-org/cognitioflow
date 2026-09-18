"""Controls that could only be used with a mouse.

Everything built from an innerHTML template got its click handler wired afterwards, and nothing ever
made it focusable. Measured in Chromium before the change:

    li[data-note]          tabIndex -1   — the note list could not be opened by keyboard at all
    .wk[data-wk]           tabIndex -1   — the whole Recall week / weak filter
    .sess .chk[data-sess]  tabIndex -1   — marking a planned session done
    #caseIndex .ci a       reports 0 and still is not focusable: an <a> with no href never is
"""
import re
from pathlib import Path

PAGE = (lambda s: s("index.html") + s("app.js") + s("app.css") + s("book.css"))(
    lambda n: (Path(__file__).resolve().parent.parent / "static" / n).read_text(encoding="utf-8"))


def _fn(name):
    """The body of a function, up to whatever top-level thing starts next. Not every function in
    this file ends on a line of its own, so a `\\n}` search is not reliable here."""
    at = PAGE.index(f"function {name}(")
    nxt = [m.start() for m in re.finditer(r"\n(?:async function |function |\$\(|const |let |/\* )", PAGE[at + 1:])]
    return PAGE[at:at + 1 + nxt[0]] if nxt else PAGE[at:]


def test_the_hooks_that_are_made_reachable_are_the_ones_that_were_not():
    sel = re.search(r"const KEYABLE = '([^']+)'", PAGE).group(1)
    for hook in ("[data-note]", "[data-wk]", "[data-weak]", "[data-sess]", ".cover", ".tplay"):
        assert hook in sel, f"{hook} was mouse-only and is not in KEYABLE"


def test_enter_and_space_reach_the_click_handlers_that_already_exist():
    """The handlers are assigned as .onclick after each render, so the key handler calls click()
    rather than duplicating them. Space is prevented because it would scroll the page."""
    at = PAGE.index("document.addEventListener('keydown', e => {")
    h = PAGE[at:PAGE.index("});", at)]
    assert "'Enter'" in h and "' '" in h
    assert "t.click()" in h
    assert "preventDefault" in h


def test_a_done_tick_is_a_checkbox_and_the_rest_are_buttons():
    """role matters to a screen reader: the session tick toggles, it does not navigate."""
    f = _fn("keyable")
    assert "'role','checkbox'" in f.replace(" ", "") and "aria-checked" in f
    assert "'role','button'" in f.replace(" ", "")
    assert "hasAttribute('role')" in f, "an element that already declares a role keeps it"


def test_every_render_point_makes_its_own_output_reachable():
    """A list rebuilt after a filter change would otherwise come back mouse-only. applyCover() needs
    its own call because it creates .cover spans after paint() has already run."""
    assert PAGE.count("keyable(") >= 7, "helper plus one call per render point"
    for fn, where in (("applyCover", "the cover spans"), ("loadWeekDir", "the week chips")):
        assert "keyable(" in _fn(fn), f"{where} are rebuilt here and would come back unreachable"
    assert "keyable($('#noteList'))" in PAGE
    assert "keyable($('#agenda'))" in PAGE


def test_nothing_was_renamed_to_achieve_it():
    """CLAUDE.md: keep every id and data- attribute, and every JS-written class. This adds
    attributes at runtime and touches no template's hooks."""
    for hook in ('data-note="', 'data-wk="', 'data-sess="', 'class="wk '):
        assert hook in PAGE, f"{hook} disappeared — a hook was renamed"
    # .cover is built in JS rather than written as markup, so it is checked where it is set
    assert "span.className='cover'" in PAGE, ".cover is a JS-written class and must keep its name"
