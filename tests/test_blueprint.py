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


def test_build_context_leads_with_brief_then_papers_and_caps_total():
    papers = [{"name": "Practice exam 1", "text": "Q1 free movement " * 4000},
              {"name": "Resit 2024", "text": "Q1 direct effect " * 4000}]
    ctx = bp.build_context(papers, syllabus_block="Week 1 — Foundations",
                           exam_format="Two IRAC cases", method="Applicability -> justification")
    assert ctx.index("EXAM FORMAT") < ctx.index("SYLLABUS") < ctx.index("PAST PAPERS")
    assert '<paper name="Practice exam 1">' in ctx
    assert len(ctx) <= bp.TOTAL_CHARS + 2000   # per/total caps hold, allowing for the framing text


def test_build_context_skips_empty_papers_and_handles_none():
    assert bp.build_context(None) == ""
    ctx = bp.build_context([{"name": "x", "text": "   "}], exam_format="One essay")
    assert "PAST PAPERS" not in ctx and "EXAM FORMAT" in ctx


# ---- the block that focuses the tutor + generators -------------------------

def test_examined_topics_reads_the_applied_blueprint():
    assert [t["topic"] for t in bp.examined_topics(APPLIED)] == ["Free movement of goods", "Direct effect"]
    assert bp.examined_topics({}) == [] and bp.examined_topics(None) == []


def test_blueprint_block_names_weight_format_and_capped_doctrines():
    blk = bp.blueprint_block(APPLIED)
    assert blk.startswith(bp.BLUEPRINT_HEADER)
    assert "- Free movement of goods — 60% · IRAC case/essay · Art 34 TFEU; Cassis; Keck" in blk
    assert "Dassonville" not in blk                         # 4th doctrine dropped by the cap
    assert "Answer method the exam rewards: Applicability" in blk


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
