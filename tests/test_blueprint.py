"""blueprint: what a course examines, weighted from its past papers. Pure, no database, no model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import blueprint as bp  # noqa: E402
import course_brief as cb  # noqa: E402


APPLIED = {bp.BLUEPRINT_KEY: {
    "topics": [
        {"topic": "Free movement of goods", "weight": 60, "formats": ["IRAC case", "essay"],
         "doctrines": ["Art 34 TFEU", "Cassis", "Keck", "Dassonville"]},
        {"topic": "Direct effect", "weight": 40, "formats": ["short answer"], "doctrines": ["Van Gend"]},
    ],
    "method": "Applicability then justification then proportionality.",
}}


def test_weight_clamps_and_tolerates_junk():
    assert bp._weight(37) == 37
    assert bp._weight("40") == 40
    assert bp._weight(130) == 100 and bp._weight(-5) == 0
    assert bp._weight(None) == 0 and bp._weight("lots") == 0


def test_items_dedupes_trims_and_caps():
    assert bp._items("Art 34 TFEU") == ["Art 34 TFEU"]
    assert bp._items(["a", "A", " a ", "b"]) == ["a", "b"]           # case-insensitive dedupe
    assert len(bp._items([str(i) for i in range(20)])) == bp.MAX_LIST
    assert bp._items({"not": "a list"}) == []


def test_normalise_renormalises_weights_to_100_and_sorts():
    raw = {"topics": [
        {"topic": "Free movement of goods", "weight": 30},
        {"topic": "Direct effect", "weight": 10},
        {"topic": "State liability", "weight": 10},
    ]}
    out = bp.normalise_blueprint(raw)
    assert sum(t["weight"] for t in out["topics"]) == 100
    assert [t["topic"] for t in out["topics"]][0] == "Free movement of goods"   # heaviest first
    assert out["topics"][0]["weight"] == 60


def test_normalise_merges_same_named_topics():
    raw = {"topics": [
        {"topic": "Direct effect", "weight": 20, "doctrines": ["Van Gend"], "seen_in": ["2023"]},
        {"topic": "direct effect", "weight": 20, "doctrines": ["Art 288"], "seen_in": ["2024"]},
    ]}
    out = bp.normalise_blueprint(raw)
    assert len(out["topics"]) == 1
    t = out["topics"][0]
    assert t["weight"] == 100
    assert set(t["doctrines"]) == {"Van Gend", "Art 288"}
    assert set(t["seen_in"]) == {"2023", "2024"}


def test_normalise_defaults_confidence_and_drops_nameless_rows():
    out = bp.normalise_blueprint({"topics": [
        {"topic": "Proportionality", "weight": 5, "confidence": "HIGH"},
        {"weight": 50},                      # no name -> dropped
        "not an object",                     # ignored
    ]})
    assert [t["topic"] for t in out["topics"]] == ["Proportionality"]
    assert out["topics"][0]["confidence"] == "high"


def test_normalise_caps_topic_count():
    raw = {"topics": [{"topic": f"Topic {i}", "weight": 1} for i in range(40)]}
    assert len(bp.normalise_blueprint(raw)["topics"]) == bp.MAX_TOPICS


def test_normalise_accepts_a_bare_list_and_zero_weights():
    out = bp.normalise_blueprint([{"topic": "A"}, {"topic": "B"}])   # all weights 0 -> left at 0, no divide by zero
    assert len(out["topics"]) == 2 and sum(t["weight"] for t in out["topics"]) == 0


def test_normalise_rejects_nonsense():
    for bad in (None, 42, "text", {"topics": "nope"}):
        try:
            bp.normalise_blueprint(bad)
            assert False, f"expected BlueprintError for {bad!r}"
        except bp.BlueprintError:
            pass


def test_build_context_leads_with_objectives_then_papers_and_caps_total():
    papers = [{"name": "Practice exam 1", "text": "Q1 free movement " * 4000},
              {"name": "Resit 2024", "text": "Q1 direct effect " * 4000}]
    ctx = bp.build_context(papers, syllabus_block="Week 1 — Foundations",
                           exam_format="Two IRAC cases", method="Applicability -> justification")
    # the stated learning objectives / syllabus are the primary input, so they come first (pitch plan row 1)
    assert ctx.index("STATED LEARNING OBJECTIVES AND SYLLABUS") < ctx.index("STUDY PAPERS")
    # the exam format and the marking method are no longer sent: the model described the exam on screen
    assert "IRAC" not in ctx and "Applicability" not in ctx and "EXAM FORMAT" not in ctx
    assert '<paper name="Practice exam 1">' in ctx
    assert len(ctx) <= bp.TOTAL_CHARS + 2000   # per/total caps hold, allowing for the framing text


def test_build_context_skips_empty_papers_and_handles_none():
    assert bp.build_context(None) == ""
    assert bp.build_context([{"name": "x", "text": "   "}], exam_format="One essay") == ""


# ---- the block that focuses the tutor + generators -------------------------

def test_examined_topics_reads_the_applied_blueprint():
    assert [t["topic"] for t in bp.examined_topics(APPLIED)] == ["Free movement of goods", "Direct effect"]
    assert bp.examined_topics({}) == [] and bp.examined_topics(None) == []


def test_blueprint_block_names_share_and_capped_doctrines_but_no_exam_talk():
    blk = bp.blueprint_block(APPLIED)
    assert blk.startswith(bp.BLUEPRINT_HEADER)
    assert "- Free movement of goods — 60% of the syllabus · Art 34 TFEU; Cassis; Keck" in blk
    assert "Dassonville" not in blk                         # 4th doctrine dropped by the cap
    # B5: no question formats, no answer method, no "what this course examines"
    assert "IRAC" not in blk and "method" not in blk.lower() and "EXAM FOCUS" not in blk
    assert "not a prediction" in bp.BLUEPRINT_HEADER


def test_strip_blueprint_removes_the_legacy_exam_focus_header_too():
    legacy = bp.LEGACY_HEADERS[0] + "\n- Free movement of goods — 60% · IRAC case"
    assert bp.strip_blueprint("Hand-written prompt.\n" + legacy) == "Hand-written prompt."
    # a prompt stored before the relabel recompiles to exactly one block, in the new wording
    once = cb.course_prompt(APPLIED, "EU", "Hand-written prompt.\n" + legacy)
    assert "EXAM FOCUS" not in once and once.count(bp.BLUEPRINT_HEADER) == 1


def test_blueprint_block_empty_without_a_blueprint():
    assert bp.blueprint_block({}) == "" and bp.blueprint_block({bp.BLUEPRINT_KEY: {"topics": []}}) == ""


def test_strip_blueprint_is_idempotent():
    stored = "Some hand-written prompt.\n" + bp.blueprint_block(APPLIED)
    assert bp.strip_blueprint(stored) == "Some hand-written prompt."
    assert bp.strip_blueprint("no block here") == "no block here"


# ---- it reaches the compiled course prompt ---------------------------------

def test_compile_prompt_appends_exam_focus_when_applied():
    p = cb.compile_prompt({"method": "IRAC.", **APPLIED}, "European Law")
    assert bp.BLUEPRINT_HEADER in p and "Free movement of goods — 60%" in p
    assert bp.BLUEPRINT_HEADER not in cb.compile_prompt({"method": "IRAC."}, "European Law")


def test_blueprint_rides_a_hand_written_prompt_without_stacking():
    # a brief that holds only a blueprint is still "empty" (a reference block, like the syllabus)
    assert cb.brief_is_empty(APPLIED) is True
    once = cb.course_prompt(APPLIED, "EU", "Hand-written prompt.")
    assert once.count(bp.BLUEPRINT_HEADER) == 1 and once.startswith("Hand-written prompt.")
    twice = cb.course_prompt(APPLIED, "EU", once)      # recompiling must not stack a second block
    assert twice.count(bp.BLUEPRINT_HEADER) == 1 and twice == once


def test_rules_frame_coverage_of_stated_objectives_not_exam_prediction():
    # pitch plan row 1 / B5: the blueprint is coverage of stated learning objectives, never "what the exam tests"
    assert "STATED LEARNING OBJECTIVES" in bp.RULES
    assert "never a prediction" in bp.RULES
    assert "Do not describe any exam" in bp.RULES
    assert '"formats"' not in bp.RULES and '"exam_format"' not in bp.RULES and '"method"' not in bp.RULES
    assert "at least one" in bp.RULES          # every topic carries a doctrine tag (plan row 1)


def test_weights_are_the_share_of_syllabus_weeks_and_stable():
    raw = {"topics": [
        {"topic": "Free movement of goods", "weeks": [3, 4], "objectives": [2], "weight": 5},
        {"topic": "Keck selling arrangements", "weeks": [4], "weight": 90},
        {"topic": "Direct effect", "seen_in": ["Week 1", "Weeks 2-3"], "weight": 5},
    ]}
    out = bp.normalise_blueprint(raw, source_papers=[])
    w = {t["topic"]: t["weight"] for t in out["topics"]}
    # 4 weeks; week 3 shared by goods + direct effect, week 4 by goods + Keck -> each counts half
    assert w == {"Direct effect": 63, "Free movement of goods": 25, "Keck selling arrangements": 12}
    assert out["basis"] == "weeks" and out["weeks_total"] == 4
    assert out["exam_format"] == "" and out["method"] == ""
    # the model's own weights are ignored when weeks are known, so a rebuild with the same weeks gives the same %
    again = bp.normalise_blueprint(out)
    assert [(t["topic"], t["weight"]) for t in again["topics"]] == [(t["topic"], t["weight"]) for t in out["topics"]]


def test_model_weights_only_when_a_topic_names_no_week():
    out = bp.normalise_blueprint({"topics": [{"topic": "A", "weeks": [1], "weight": 30},
                                             {"topic": "B", "weight": 10}]})
    assert out["basis"] == "model" and [t["weight"] for t in out["topics"]] == [75, 25]


def test_confidence_is_derived_from_objectives_and_weeks_never_from_papers():
    raw = {"topics": [{"topic": "Goods", "weeks": [3], "objectives": [1], "confidence": "low"},
                      {"topic": "Keck", "weeks": [4], "confidence": "high"},
                      {"topic": "Loose", "confidence": "high"}]}
    out = bp.normalise_blueprint(raw, source_papers=["Exam 2024.pdf"])   # a paper no longer lifts anything
    assert {t["topic"]: t["confidence"] for t in out["topics"]} == {"Goods": "high", "Keck": "medium", "Loose": "low"}
    assert out["objectives_stated"] is True
    assert "Objective 1" in out["topics"][0]["seen_in"] or "Objective 1" in out["topics"][1]["seen_in"]


def test_formats_are_dropped():
    out = bp.normalise_blueprint({"topics": [{"topic": "Goods", "weeks": [1], "formats": ["IRAC case", "compare"]}]})
    assert out["topics"][0]["formats"] == []


# ---- stated learning objectives reach the map through the brief ------------

def test_learning_objectives_are_a_brief_field_and_feed_the_block_numbered():
    assert "learning_objectives" in [k for k, _, _ in cb.BRIEF_FIELDS]
    brief = {"learning_objectives": "1. Explain the free movement of goods.\n- Apply Art 34 TFEU to a measure\n\n",
             cb.SYLLABUS_KEY: {"weeks": [{"week": "1", "title": "Goods", "topics": ["Art 34"], "readings": []}]}}
    blk = cb.syllabus_block(brief)
    assert blk.index(cb.SYLLABUS_HEADER) < blk.index(cb.OBJECTIVES_HEADER)
    assert "Objective 1: Explain the free movement of goods." in blk
    assert "Objective 2: Apply Art 34 TFEU to a measure." in blk
    # objectives alone (no syllabus read yet) still give the map something to build from
    assert cb.syllabus_block({"learning_objectives": "Explain direct effect"}).startswith(cb.OBJECTIVES_HEADER)
    assert cb.syllabus_block({}) == ""


def test_saving_course_settings_keeps_a_saved_coverage_map():
    old = {"lecturer": "X", cb.SYLLABUS_KEY: {"weeks": [{"week": "1", "title": "A", "topics": [], "readings": []}]},
           **APPLIED}
    kept = cb.keep_syllabus({"lecturer": "Y", "learning_objectives": "Explain goods"}, old)
    assert kept[bp.BLUEPRINT_KEY] == APPLIED[bp.BLUEPRINT_KEY] and kept[cb.SYLLABUS_KEY]["weeks"]


def test_long_notes_are_cut_at_a_word_with_an_ellipsis():
    long = "national-level enforcement including direct effect, state liability, and effective judicial protection " * 4
    note = bp.normalise_blueprint({"topics": [{"topic": "A", "weeks": [1], "note": long}]})["topics"][0]["note"]
    assert len(note) <= 240 and note.endswith("…") and not note.endswith(" …")
    assert long.startswith(note[:-1])
