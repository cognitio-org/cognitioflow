"""
Tests: the single-file UI's layout rules, asserted against static/index.html.

The UI has no build step and no component boundaries, so a screen-layout class and a
JS-written class can quietly collide. This guards the collision that bit, fixed in #47.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", HTML, re.S).group(1), flags=re.S)

# A `.tutor` selector is safe when it cannot match a bare <div class="advb tutor">. That means it
# either names the bubble itself, or anchors the class to the screen it belongs to. How it anchors
# is the stylesheet's business — `.screen>` today, an id or another ancestor tomorrow — so accept
# any of them and fail only on a `.tutor` standing on its own.
SAFE = (".advb", "#tutor", ".screen>", ".screen >")


def _selector_around(css: str, at: int) -> str:
    """The comma-separated selector segment that the occurrence at `at` belongs to."""
    start = max(css.rfind("{", 0, at), css.rfind("}", 0, at)) + 1
    return next(s for s in css[start:css.index("{", at)].split(",") if ".tutor" in s)


def test_the_tutor_screen_grid_never_reaches_a_chat_bubble():
    """
    advBubble() and courtSay() both write `class="advb tutor"`, so a bare `.tutor` rule styles
    every tutor bubble in Tutor, Advocate and the courtroom as if it were the whole screen —
    display:grid in a 230px column, at the screen's height. Measured before #47 fixed it, a
    `.advb` bubble computed to display:block at 581px wide and 38px tall; a `.advb.tutor`
    computed to display:grid, grid-template-columns 230px 0px, 272px wide and the full height of
    the viewport. The verdict label ended up alone in a narrow column and the first bubble filled
    the Advocate screen on its own.
    """
    hits = [m.start() for m in re.finditer(r"\.tutor\b", CSS)]
    assert hits, "no .tutor rules found — has the Tutor screen been renamed?"
    for at in hits:
        sel = _selector_around(CSS, at)
        assert any(s in sel for s in SAFE), \
            f"unscoped .tutor rule would style every chat bubble as the whole screen: {sel.strip()!r}"


def test_the_bubble_classes_the_screen_rules_are_scoped_against_are_still_written():
    """If the JS stops writing `advb tutor`, the scoping above is protecting nothing — say so here
    rather than letting the guard pass vacuously."""
    assert HTML.count("d.className='advb '+who") == 2, "advBubble/courtSay no longer write `advb <who>`"
    assert re.search(r"advBubble\('tutor'", HTML) and re.search(r"courtSay\('tutor'", HTML)
