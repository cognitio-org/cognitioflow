"""
Tests: the single-file UI's layout rules, asserted against static/index.html.

The UI has no build step and no component boundaries, so a screen-layout class and a
JS-written class can quietly collide. These guard the collisions that have bitten.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", HTML, re.S).group(1), flags=re.S)


def _selector_around(css: str, at: int) -> str:
    """The comma-separated selector segment that the occurrence at `at` belongs to."""
    start = max(css.rfind("{", 0, at), css.rfind("}", 0, at)) + 1
    return next(s for s in css[start:css.index("{", at)].split(",") if ".tutor" in s)


def test_the_tutor_screen_grid_never_reaches_a_chat_bubble():
    """
    advBubble() and courtSay() both write `class="advb tutor"`, so a bare `.tutor` rule styles
    every tutor bubble in Tutor, Advocate and the courtroom as if it were the whole screen —
    display:grid in a 230px column, at the screen's height. Every screen rule stays under #tutor.
    """
    hits = [m.start() for m in re.finditer(r"\.tutor\b", CSS)]
    assert hits, "no .tutor rules found — has the Tutor screen been renamed?"
    for at in hits:
        sel = _selector_around(CSS, at)
        assert "#tutor" in sel or ".advb" in sel, f"unscoped .tutor rule would hit chat bubbles: {sel.strip()!r}"


def test_the_bubble_classes_the_screen_rules_are_scoped_against_are_still_written():
    """If the JS stops writing `advb tutor`, the scoping above is protecting nothing — say so here."""
    assert HTML.count("d.className='advb '+who") == 2, "advBubble/courtSay no longer write `advb <who>`"
    assert re.search(r"advBubble\('tutor'", HTML) and re.search(r"courtSay\('tutor'", HTML)


def test_a_failed_mermaid_render_is_cleaned_off_the_page():
    """
    mermaid 10.9.8 draws into a throwaway `#d<id>` under <body> and removes it only on success:
    a syntax error leaves its bomb graphic over the UI. The bundled build has no
    suppressErrorRendering, so render() holds the id and removes the orphan itself.
    """
    body = re.search(r"async function render\(d,raw\)\{.*?\n\}", HTML, re.S).group(0)
    assert re.search(r"const id='mm'\+", body), "render() must hold the render id to clean up after it"
    assert "mermaid.render(id," in body, "the held id must be the one mermaid renders with"
    assert "document.getElementById('d'+id)" in body, "the orphaned #d<id> container must be removed"
    assert "finally{" in body, "cleanup must run whether the render threw or not"
