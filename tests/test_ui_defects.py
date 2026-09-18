"""Five ways the page rendered wrong. Each of these shipped, and each was invisible in the source.

There is no JS test runner here and CLAUDE.md forbids adding one, so these assert against
static/index.html the way test_courses.py's palette test does. Every one fails on the page as it
stood before this change — that is the point of writing them.
"""
import re
from pathlib import Path

# index.html was split on 2026-09-18: JS to static/app.js, CSS to static/app.css
# and static/book.css. These assertions are about the shipped UI, so read all of it.
def _page_text():
    d = Path(__file__).resolve().parent.parent / "static"
    out = []
    for n in ("index.html", "app.js", "app.css", "book.css", "app-after.css"):
        f = d / n
        if f.exists():
            out.append(f.read_text(encoding="utf-8"))
    return chr(10).join(out)


PAGE = _page_text()


def test_the_bubble_class_the_scoping_defends_against_is_still_written():
    """If the JS stops writing `advb <who>`, the scoping below is guarding nothing — say so here
    rather than letting the guard quietly become decorative. (Idea taken from #48.)"""
    assert PAGE.count("d.className='advb '+who") == 2, "advBubble/courtSay no longer write `advb <who>`"
    assert re.search(r"advBubble\('tutor'", PAGE) and re.search(r"courtSay\('tutor'", PAGE)


def test_the_screen_layouts_cannot_catch_chat_bubbles():
    """`.tutor` was the Tutor SCREEN grid, and bubbles are built in JS as `advb tutor`.

    Every bubble in the tutor, the advocate and the courtroom inherited a 230px + 1fr screen
    layout, and in focus mode a height of calc(100vh - 4.4rem) as well. The layout div is a direct
    child of .screen; the bubbles are not, so `>` is what separates them.
    """
    # PAGE already carries app.css and book.css; there is no <style> block to search any more.
    css = re.sub(r"/\*.*?\*/", "", PAGE, flags=re.S)
    for m in re.finditer(r"\.tutor\b", css):
        at = m.start()
        start = max(css.rfind("{", 0, at), css.rfind("}", 0, at)) + 1
        sel = next(s for s in css[start:css.index("{", at)].split(",") if ".tutor" in s).strip()
        if ".advb" in sel:
            continue                      # the bubble's own rule, which is the point
        assert ">.tutor" in sel, (
            f"{sel!r} reaches chat bubbles. A DESCENDANT scope such as `#tutor .tutor` is not "
            "enough — the tutor's own bubbles live inside #tutor. It has to be a child combinator.")
    assert ".screen>.tutor{display:grid" in PAGE
    assert ".screen>.notes{display:grid" in PAGE


def test_mermaid_is_measured_in_the_font_it_is_painted_in():
    """fontFamily:'inherit' measured in the <body> sandbox (sans) and painted in .noteview (serif),
    so labels overflowed the diamonds mermaid had sized for them."""
    setup = re.search(r"function mmSetup\(\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "fontFamily:'inherit'" not in setup and 'fontFamily:"inherit"' not in setup
    assert "--sans" in setup, "the family must come from the token, not a literal"
    assert ".viz svg,.viz svg text" in PAGE, "the paint side must be pinned to the same family"


def test_a_failed_diagram_does_not_leave_its_sandbox_on_the_page():
    """Mermaid appends a measuring div to <body> as 'd'+id and leaves it there on a parse error —
    the bomb graphic stuck at the foot of an unrelated screen. The catch cannot reach it."""
    render = re.search(r"async function render\(d,raw\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "finally{" in render and "getElementById('d'+mid)" in render


def test_the_diagram_theme_is_not_latched_to_the_first_render():
    """mmInit latched, so a mid-session OS theme switch kept the first theme's diagram colours."""
    assert "let mmInit" not in PAGE, "mmInit latched on first render; mmTheme tracks the scheme"
    setup = re.search(r"function mmSetup\(\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "if(mmTheme===scheme) return" in setup


def test_the_dark_accent_is_allowed_to_reach_the_page():
    """Setting --accent as an inline style on :root outranks both stylesheet rules, so the dark
    color-mix written to lighten the course colour never ran. Measured 1.87:1 before, 7.29:1 after.
    JS must set the raw --course and let the cascade derive --accent."""
    assert "setProperty('--accent'" not in PAGE, "an inline --accent kills the dark color-mix"
    assert PAGE.count("setProperty('--course'") == 2, "both the boot and the course switcher"
    assert "--accent:var(--course" in PAGE
    assert "--accent:color-mix(in oklab,var(--course" in PAGE


def test_the_arena_survives_a_cold_load_with_no_courses():
    """C() is `courses.find(...)||courses[0]`, i.e. undefined before any course exists, and
    loadArena read C().name unguarded — the Arena screen threw for a brand-new user."""
    fn = re.search(r"function loadArena\(\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "C().name" not in fn, "unguarded C() throws when the course list is empty"


def test_every_screen_is_reachable_from_the_command_palette():
    """advocate and arena — the two newest screens — could not be found by typing their name."""
    pal = re.search(r"const PAL_SCREENS=\[(.*?)\];", PAGE, re.S).group(1)
    screens = re.search(r"const SCREENS=\[(.*?)\];", PAGE, re.S).group(1)
    named = set(re.findall(r"\['(\w+)',", pal))
    assert set(re.findall(r"'(\w+)'", screens)) == named
