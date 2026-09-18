"""How a stored note is shown: the complaint was "the way the text storage is shown can look better".

Three things were wrong, all measured in Chromium against the seeded fixture notes.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = (lambda s: s("index.html") + s("app.js") + s("app.css") + s("book.css"))(
    lambda n: (Path(__file__).resolve().parent.parent / "static" / n).read_text(encoding="utf-8"))


def test_the_reading_measure_does_not_depend_on_the_element_font_size():
    """--measure was 68ch, and `ch` resolves against each element's OWN font size — so the same
    token gave an h1 a 749px box and a paragraph a 540px one, and headings, prose and lists sat on
    three different left edges. Measured after the change: every text block at x=683, width 540."""
    assert "--measure:68ch" not in PAGE, "ch makes the measure mean something different per heading"
    assert PAGE.count("--measure:36rem") == 2, "one value, meaning the same width to every block"


def test_the_measure_is_applied_to_the_text_and_not_to_the_paper():
    """Capping the container would have taken the tables and diagrams down with it. Before this the
    token never bound at all: the padding-inline clamp caps the side margin at 5rem, and reaching
    the measure on this column needs ~180px, so prose ran 94.3 characters a line at 1440 and 123.6
    at 1190. The table is still measured at the full 749px paper width."""
    rule = re.search(r"\.noteview>p,[^{]*\{([^}]*)\}", PAGE).group(0)
    assert "max-width:var(--measure)" in rule
    for tag in ("h1", "h2", "h3", "ul", "ol", "blockquote"):
        assert f".noteview>{tag}" in rule, f"{tag} must sit on the same measure as the prose"
    assert ".noteview>table" not in rule, "a table wants the whole width of the paper"


def test_routine_provenance_is_a_siglum_and_only_a_flag_is_boxed():
    """Every tag was a bordered box mid-sentence — roughly one hard-edged rectangle per line of
    prose, out-shouting the italic case names it interrupts. Weight now follows the authority
    hierarchy: WG keeps a marker, a flag stays boxed, the rest step back. chipify() is untouched."""
    base = re.search(r"\n  \.prov\{([^}]*)\}", PAGE).group(1)
    assert "border:0" in base, "routine provenance should not be a box"
    assert "vertical-align:.45em" in base, "it reads as a superior siglum"
    assert ".prov.wg::before" in PAGE, "annotated WG is top of the hierarchy and keeps its marker"
    flag = re.search(r"\.prov\.flag\{([^}]*)\}", PAGE).group(1)
    assert "border:1px solid var(--warn)" in flag, "VERIFY / CORRECTION / ADDED still demand action"
    assert "function chipify" in PAGE and "PROV[key]" in PAGE, "the renderer itself must not change"


@pytest.mark.skipif(not shutil.which("node"), reason="node is not on this machine")
def test_soft_wraps_are_joined_but_deliberate_lines_are_not():
    """render() parses with breaks:true, so every soft wrap in a stored note became a <br> — which
    is why a bullet read "Week 2 covers two foundational freedoms" and then a line beginning with a
    stranded colon. breaks:false would have been the blunt fix and is wrong: Live capture is typed
    one line per thought ([LEC] / [!] / [P]), none of which start a markdown block, so they would
    all have run together."""
    fn = re.search(r"function unwrapSoftBreaks\(md\)\{.*?\n\}", PAGE, re.S).group(0)
    cases = {
        "colon":      "- **Two freedoms**\n: (1) goods, and (2) workers.",
        "sentence":   "Union law prevails. The national\nrule is set aside.",
        "capture":    "[LEC] Dassonville is the catch-all.\n[!] Not Keck.\n[P] Schutze p.412",
        "hard_break": "first line  \nsecond line",
        "table":      "| Case | Rule |\n| --- | --- |\n| Keck | selling arrangements |",
        "fence":      "```mermaid\ngraph TD\nA --> B\n```",
        "ordered":    "1. Costa v ENEL\n2. Internationale Handelsgesellschaft",
        "bullets":    "- goods\n- workers",
    }
    script = fn + "\nconst c=" + json.dumps(cases) + ";\n" + \
        "const out={}; for(const k in c) out[k]=unwrapSoftBreaks(c[k]); console.log(JSON.stringify(out));"
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    timeout=30, check=True).stdout)

    assert got["colon"] == "- **Two freedoms**: (1) goods, and (2) workers.", \
        "the stranded colon must rejoin, and attach without a space"
    assert got["sentence"] == "Union law prevails. The national rule is set aside.", \
        "a sentence broken by a soft wrap must read as one sentence"
    for keep in ("capture", "hard_break", "table", "fence", "ordered", "bullets"):
        assert got[keep] == cases[keep], f"{keep} carries deliberate line breaks and must not be joined"
