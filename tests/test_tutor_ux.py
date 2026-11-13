"""Tutor answers on screen (pitch baseline 2026-11-13, judge 6/10): progress while waiting, markdown that reads as
markdown mid-stream, the passage behind a source tag, an AI-generated label and a flag that cannot be missed.

There is no JS test runner here and CLAUDE.md forbids adding one, so these read static/ the way
test_ui_defects.py does. Each guards a defect that shipped and was seen in the baseline screenshots.
"""
import re
from pathlib import Path

_S = Path(__file__).resolve().parent.parent / "static"
JS = (_S / "app.js").read_text(encoding="utf-8")
CSS = (_S / "app-after.css").read_text(encoding="utf-8")


def _fn(name):
    m = re.search(r"function " + name + r"\(.*?\n(?=function |async function |const |let |/\*)", JS, re.S)
    assert m, f"{name} is gone"
    return m.group(0)


def test_send_shows_each_step_from_the_stream():
    send = _fn("send")
    assert "cfStatus(d,'find')" in send, "nothing on screen while the server picks passages"
    assert "cfStatus(d,'read'" in send and "cfStatus(d,'write')" in send
    assert "cfStatusEnd(d)" in send, "the status must go when the answer is final"
    # cfLive rebuilds the bubble every 120 ms; the status has to survive that
    assert "if(d._status) d.prepend(d._status)" in _fn("cfLive")


def test_live_frames_close_open_emphasis_and_hold_back_half_tags():
    live = _fn("cfLive")
    assert "cfLiveTidy(" in live, "streaming frames are parsed raw: '**C-999/97 ' shows two stars"
    tidy = _fn("cfLiveTidy")
    assert "t+='**'" in tidy and r"\[(?:[A-Z]" in tidy


def test_loose_source_tags_are_normalised_before_parsing():
    assert "render(d,cfTagNorm(raw))" in _fn("send")
    assert "render(d,cfTagNorm(body))" in JS, "history answers keep the raw bracket tags"
    # [LECTURE, *Lecture 2*] and [OUTSIDE FILES — unverified] were the two shapes left as raw text
    pat = re.search(r"const CF_TAG_ANY=/(.+?)/g;", JS).group(1)
    rx = re.compile(pat.replace("\\/", "/"))
    for tag in ("[LECTURE, *Lecture 2 notes*]", "[OUTSIDE FILES — unverified, do not cite]", "[WG: Assignment 4]", "[SLIDES]"):
        assert rx.search(tag), tag


def test_the_chip_regex_is_not_tested_with_a_global_lastindex():
    chips = _fn("cfChips")
    assert "CF_SRC1.test(" in chips and "CF_SRC.test(" not in chips


def test_every_answer_carries_the_ai_label_and_the_flag_is_a_callout():
    assert "AI-generated — verify before relying on it" in JS
    assert JS.count("cfFoot(d)") >= 3, "live answers, history answers and the study desk"
    flag = _fn("cfFlagBox")
    assert "Not in your materials" in flag and "check before you rely on" in flag
    assert "w.style.cssText" not in _fn("send"), "the flag is styled by class, not an inline grey line"
    assert ".cf-flag{" in CSS and "var(--warn)" in CSS.split(".cf-flag{", 1)[1].split("}", 1)[0]


def test_source_panel_reads_only_ticked_files_and_never_invents_an_ecli():
    panel = _fn("cfSourcePanel")
    assert "h.kind==='file'&&ids.has(h.id)" in panel, "unticked files or notes would pass as the source"
    assert "textContent" in panel and "innerHTML" not in panel, "file text must not be parsed as HTML"
    assert "does not prove" in panel
    # ECLIs and case numbers come from the answer line or the passage, nothing else
    assert "cfCites(line)" in panel and "cfCites(ex.pre+ex.hit+ex.post)" in panel


def test_source_chips_are_keyboard_reachable():
    src = _fn("cfSources")
    assert "tabIndex=0" in src and "role','button'" in src and "e.key==='Enter'" in src


def test_status_pulse_respects_reduced_motion():
    assert "tpulse" in CSS
    for line in CSS.splitlines():
        if "animation:tpulse" in line:
            assert "prefers-reduced-motion:no-preference" in line
