"""Colour that only worked in one theme.

The rating row hard-coded its light values and never redefined them for dark, and --rule was below
the 3:1 WCAG 1.4.11 asks of a meaningful boundary in BOTH themes. These parse the token block and
compute the ratios, rather than checking that a selector exists — a selector check would pass on a
palette that is unreadable.
"""
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")


def _tokens():
    """{theme: {token: '#rrggbb'}} for the two :root blocks."""
    light = re.search(r":root\{(--ink:.*?)\}", PAGE, re.S).group(1)
    dark = re.search(r"prefers-color-scheme:dark\)\{:root\{(.*?)\}", PAGE, re.S).group(1)
    grab = lambda blob: dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", blob))
    out = {"light": grab(light), "dark": dict(grab(light), **grab(dark))}
    return out


def _lum(h):
    c = [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    f = lambda v: (v / 255) / 12.92 if v / 255 <= .04045 else (((v / 255) + .055) / 1.055) ** 2.4
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2])


def ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + .05) / (lo + .05), 2)


def test_every_rating_button_is_readable_in_both_themes():
    """A 20-minute dark recall session is graded through these four. Measured on dark --paper before
    the change: Again 3.55:1, Hard 4.39:1, Good 2.78:1 — Good being the one pressed most."""
    row = next(l for l in PAGE.splitlines() if ".rate.again{" in l)
    for name in ("again", "hard", "good", "easy"):
        assert not re.search(rf"\.rate\.{name}\{{border-color:#", row), \
            f".rate.{name} hard-codes a colour, so it cannot follow the theme"
    toks = _tokens()
    for theme, vals in toks.items():
        for label, tok in (("Again", "--bad"), ("Hard", "--warn"), ("Good", "--ok")):
            r = ratio(vals[tok], vals["--paper"])
            assert r >= 4.5, f"{label} ({tok}) is {r}:1 on {theme} --paper; text needs 4.5:1"


def test_a_boundary_that_carries_meaning_can_be_seen():
    """--rule is 1.19:1 on --raised in dark, which is why a case-map table's row rules disappear —
    and the row rule is the only thing binding a case to the rule it gives you. WCAG 1.4.11 asks
    3:1 of a non-text boundary. --rule stays for decorative hairlines; structure uses the new token."""
    assert ".noteview td{border-bottom:1px solid var(--rule-strong)}" in PAGE
    for theme, vals in _tokens().items():
        assert "--rule-strong" in vals, f"--rule-strong is not defined for {theme}"
        for surface in ("--paper", "--raised", "--faint"):
            r = ratio(vals["--rule-strong"], vals[surface])
            assert r >= 3.0, f"--rule-strong is {r}:1 on {theme} {surface}; a boundary needs 3:1"


def test_one_red_means_one_thing():
    """#b3524e, #c0563c and #b3261e all meant wrong / missed / recording, in three shades that never
    agreed with each other and none of which changed for dark."""
    for stale in ("#b3524e", "#c0563c", "#b3261e"):
        assert stale not in PAGE, f"{stale} is a hard-coded red that does not follow the theme"
    toks = _tokens()
    for theme, vals in toks.items():
        assert "--bad" in vals, f"--bad is not defined for {theme}"
