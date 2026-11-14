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
    # w4 (skeptic): a stored "high" on a topic tied to no week and no objective reads as implied, not "objective"
    assert out["topics"][0]["confidence"] == "low"


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


def test_build_context_sends_only_the_objectives_and_syllabus_never_papers():
    papers = [{"name": "Practice exam 1", "text": "Q1 free movement " * 4000},
              {"name": "Resit 2024", "text": "Q1 direct effect " * 4000}]
    ctx = bp.build_context(papers, syllabus_block="Week 1 — Foundations",
                           exam_format="Two IRAC cases", method="Applicability -> justification")
    assert ctx.startswith("STATED LEARNING OBJECTIVES AND SYLLABUS")
    # w3 skeptic: past-exam papers were still fed to the model; the exam format and method never are
    assert "Practice exam" not in ctx and "<paper" not in ctx and "free movement" not in ctx
    assert "IRAC" not in ctx and "Applicability" not in ctx and "EXAM FORMAT" not in ctx
    bp.normalise_blueprint({"topics": []})     # consume the scope build_context left for this request


def test_build_context_without_a_syllabus_asks_for_an_empty_map():
    assert '"topics": []' in bp.build_context(None)
    assert "Resit" not in bp.build_context([{"name": "Resit", "text": "Q1"}], exam_format="One essay")
    bp.normalise_blueprint({"topics": []})


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
    # 2.5, 1 and 0.5 of 4 weeks, each rounded on its own (half up) — never nudged to make the sum 100
    assert w == {"Direct effect": 63, "Free movement of goods": 25, "Keck selling arrangements": 13}
    assert out["basis"] == "weeks" and out["weeks_total"] == 4
    assert out["exam_format"] == "" and out["method"] == ""
    # the model's own weights are ignored when weeks are known, so a rebuild with the same weeks gives the same %
    again = bp.normalise_blueprint(out)
    assert [(t["topic"], t["weight"]) for t in again["topics"]] == [(t["topic"], t["weight"]) for t in out["topics"]]


def test_legacy_maps_without_weeks_keep_their_stored_weights():
    # a map saved before topics named weeks: the only numbers there are; nothing a current build produces
    out = bp.normalise_blueprint({"topics": [{"topic": "A", "weight": 30}, {"topic": "B", "weight": 10}]})
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


# ---- w3 regressions: judge/skeptic majors reproduced on e48405c -------------

def test_one_weekless_topic_does_not_zero_every_bar():
    # MAJOR 1: only the fields RULES asks for (no "weight"). X spans weeks 1-3, Y names no week.
    out = bp.normalise_blueprint({"topics": [{"topic": "X", "weeks": [1, 2, 3], "objectives": [1]},
                                             {"topic": "Y", "weeks": [], "objectives": [2]}]})
    w = {t["topic"]: t for t in out["topics"]}
    assert out["basis"] == "weeks"
    assert w["X"]["weight"] == 100 and w["X"].get("share") == 3 and w["X"].get("share_of") == 3
    assert w["Y"]["weight"] == 0 and w["Y"].get("share") == 0   # shown as "not tied to a syllabus week", no %


def test_objectives_only_course_gets_a_share_of_the_objectives_not_zero():
    # MAJOR 1b: a course with learning objectives but no syllabus read yet
    out = bp.normalise_blueprint({"topics": [{"topic": "X", "objectives": [1, 2]},
                                             {"topic": "Y", "objectives": [2, 3]},
                                             {"topic": "Z", "objectives": [4]}]})
    w = {t["topic"]: t["weight"] for t in out["topics"]}
    assert out["basis"] == "objectives" and out.get("objectives_total") == 4
    assert w == {"X": 38, "Y": 38, "Z": 25}                    # 1.5, 1.5 and 1 of 4 objectives


def test_rules_never_ask_for_a_weight():
    assert '"weight"' not in bp.RULES


def test_invented_weeks_and_objectives_are_dropped():
    # MAJOR 2: week 30 and objective 9 do not exist in a 4-week, 6-objective course
    raw = {"topics": [{"topic": "A", "weeks": [1, 2], "objectives": [1]},
                      {"topic": "B", "weeks": [3, 30], "objectives": [9]},
                      {"topic": "C", "seen_in": ["Week 31", "Objective 12"]}]}
    blk = cb.syllabus_block({"learning_objectives": "\n".join(f"Objective text {i}" for i in range(1, 7)),
                             cb.SYLLABUS_KEY: {"weeks": [{"week": str(n), "title": "T", "topics": [], "readings": []}
                                                         for n in (1, 2, 3, 4)]}})
    bp.build_context([], syllabus_block=blk)             # what run.py's extract does, back to back
    out = bp.normalise_blueprint(raw, source_papers=[])
    t = {x["topic"]: x for x in out["topics"]}
    assert t["B"]["weeks"] == [3] and t["B"]["objectives"] == [] and t["B"]["confidence"] == "medium"
    assert t["C"]["weeks"] == [] and t["C"]["objectives"] == [] and t["C"]["confidence"] == "low"
    assert "Week 31" not in t["C"]["seen_in"] and "Objective 12" not in t["C"]["seen_in"]
    # the denominator is the real syllabus (4 weeks), not the weeks the model happened to map (4 incl. week 30)
    assert out["weeks_total"] == 4 and out.get("weeks_unmapped") == [4]
    assert t["A"]["weight"] == 50 and t["B"]["weight"] == 25   # 2 of 4, 1 of 4 — week 30 takes nothing
    # explicit arguments (the pending run.py patch passes them) give the same answer
    again = bp.normalise_blueprint(raw, source_papers=[], syllabus_weeks=[1, 2, 3, 4], objectives=6)
    assert [(x["topic"], x["weight"], x["weeks"]) for x in again["topics"]] == \
           [(x["topic"], x["weight"], x["weeks"]) for x in out["topics"]]


def test_extract_scope_is_consumed_and_never_checks_a_later_call():
    blk = cb.syllabus_block({"learning_objectives": "Explain goods\nApply Art 34",
                             cb.SYLLABUS_KEY: {"weeks": [{"week": str(n), "title": "T", "topics": [], "readings": []}
                                                         for n in (1, 2, 3)]}})
    assert bp.scope_from_block(blk) == ([1, 2, 3], ["Explain goods.", "Apply Art 34."])
    bp.build_context([], syllabus_block=blk)
    out = bp.normalise_blueprint({"topics": [{"topic": "A", "weeks": [1, 9], "objectives": [2, 7]}]},
                                 source_papers=[])
    assert out["topics"][0]["weeks"] == [1] and out["topics"][0]["objectives"] == [2]
    assert out["weeks_total"] == 3 and out["objectives_total"] == 2
    later = bp.normalise_blueprint({"topics": [{"topic": "A", "weeks": [9]}]})
    assert later["topics"][0]["weeks"] == [9]


def test_equal_weeks_show_equal_percent_and_a_resave_keeps_the_real_denominator():
    # judge: weeks 1-2, 9-10, 11-12 of 12 showed 18/17/17 because rounding was forced to sum to 100
    topics = [{"topic": f"T{i}", "weeks": [2 * i + 1, 2 * i + 2]} for i in range(6)]
    out = bp.normalise_blueprint({"topics": topics}, syllabus_weeks=list(range(1, 13)), objectives=[])
    assert {t["weight"] for t in out["topics"]} == {17} and {t["share"] for t in out["topics"]} == {2}
    # Save posts the proposal back without the course scope; the 12-week denominator survives on the topics
    partial = bp.normalise_blueprint({"topics": topics[:5]}, syllabus_weeks=list(range(1, 13)), objectives=[])
    assert partial["weeks_unmapped"] == [11, 12]
    again = bp.normalise_blueprint(partial)
    assert again["weeks_total"] == 12 and {t["weight"] for t in again["topics"]} == {17}


def test_objectives_basis_is_named_in_the_tutor_block():
    out = bp.normalise_blueprint({"topics": [{"topic": "X", "objectives": [1], "doctrines": ["Art 34"]}]},
                                 syllabus_weeks=[], objectives=2)
    blk = bp.blueprint_block({bp.BLUEPRINT_KEY: out})
    assert "50% of the stated learning objectives" in blk
