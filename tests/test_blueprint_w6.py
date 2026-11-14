"""Coverage map w6: the demo course says its study data is seeded (M7), the focus list reads as one (M8),
another course with the demo's week titles does not borrow its chips, and the saved demo map is pinned (M6d)."""
import json
import re
from pathlib import Path

import blueprint as bp
import course_brief as cb

ROOT = Path(__file__).resolve().parents[1]
SEED = json.loads((ROOT / "docs" / "demo" / "eu-public-demo-course.json").read_text())
JS = (ROOT / "static" / "app.js").read_text()
HTML = (ROOT / "static" / "index.html").read_text()
CSS = (ROOT / "static" / "app.css").read_text()


def test_seed_brief_labels_its_study_data_as_demo_and_the_brief_accepts_it():
    note = SEED["brief"]["study_data_note"]
    assert note.lower().startswith("demo study data") and "not a real student" in note
    assert cb.normalise_brief(SEED["brief"])["study_data_note"] == note


def test_study_data_note_is_display_only_never_in_the_tutor_prompt():
    prompt = cb.compile_prompt(cb.normalise_brief(SEED["brief"]), SEED["course"]["name"])
    assert "Demo study data" not in prompt and "seeded for this demo" not in prompt


def test_readiness_panel_carries_the_demo_label_slot_and_the_rule_for_the_bands():
    assert 'id="rdDemo"' in HTML and "rdDemo" in JS
    assert "Ready: 80% or more" in HTML and "gap: no cards on it yet" in HTML
    assert "score ${pct}%" in JS          # each row's band can be recomputed from the stated rule


def test_study_next_is_labelled_a_focus_list_and_opens_a_topic():
    assert "Focus list — study next" in JS and "data-rdgo" in JS and "const rdGo" in JS


def test_no_objectives_empty_state_does_not_promise_stated_objectives():
    assert "co.objs.length&&co.weeks.length?'the course’s stated learning objectives and syllabus weeks'" in JS


def test_pack_codes_are_shown_once():
    assert "const code=" in JS and "Objective ${n}${code?" in JS


def test_small_screens_give_both_panels_their_own_clearance_from_the_fixed_strip():
    assert re.search(r"#blueprintPanel,#readinessPanel\{padding-bottom:3\.[0-9]+rem\}", CSS)


def test_another_course_with_the_demo_week_titles_keeps_the_models_chips():
    title = SEED["syllabus"]["weeks"][0]["title"]
    assert bp.curated_chips(title, ["Describe the law of contract."]) is None
    assert bp.curated_chips(title, [SEED["brief"]["learning_objectives"].splitlines()[0]])


def test_saved_demo_map_is_pinned_and_its_chips_are_the_written_ones():
    # M6(d): any change to the map text fails here and reopens the human legal read (M6c). The pinned value is
    # the hash of the map Matej reads; until that read is logged in HISTORY it is a candidate, not an approval.
    import hashlib
    saved = json.loads((ROOT / "docs" / "demo" / "eu-demo-saved-map.json").read_text())
    h = hashlib.sha256(json.dumps(saved["topics"], sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":")).encode()).hexdigest()
    assert h == "bddfa1985bace005f7b88d1e470358cd812ceaa5f50e471647cbf991809d71f8"
    weeks = {w["week"]: w["title"] for w in SEED["syllabus"]["weeks"]}
    for t in saved["topics"]:
        assert t["doctrines"] == bp.curated_chips(weeks[t["weeks"][0]], [SEED["brief"]["learning_objectives"].splitlines()[0]])
