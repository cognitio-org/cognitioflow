"""Coverage map w5: the demo course's authority chips are WRITTEN, not asked for (blueprint_authorities.py).

Pure: no database, no network. Checks the table against the source index copied from the demo pack
(docs/demo/eu-demo-sources-index.json) and, when the pack is on this machine, against the source files themselves.
"""
import json
import os
import re
from pathlib import Path

import pytest

import blueprint as bp
import course_brief as cb

DEMO_OBJ_SAMPLE = "A1. State the prohibitions in Articles 34 and 35 TFEU and the derogation grounds."
ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs" / "demo"
SEED = json.loads((DEMO / "eu-public-demo-course.json").read_text())
INDEX = json.loads((DEMO / "eu-demo-sources-index.json").read_text())
PACK = Path(os.environ.get("CF_DEMO_PACK", Path.home() / "reports" / "cf-pitch" / "demo-course"))
WEEKS = SEED["syllabus"]["weeks"]
BRIEF = SEED["brief"] | {"syllabus": SEED["syllabus"]}
SYL = cb.syllabus_block(BRIEF)

# Article -> what it may be cited for, and in which demo weeks it may appear. Kept next to the test on purpose:
# adding an article to the table without a proposition here fails.
PAIRING = {
    34: ("the prohibition of import restrictions and measures of equivalent effect", range(1, 7)),
    35: ("the prohibition of export restrictions and measures of equivalent effect", [1]),
    36: ("the derogation grounds", [1, 4, 5, 6]),
    267: ("the preliminary reference procedure", [7, 9]),
    288: ("the legal effect of directives", [9]),
}


def _rows():
    for n, w in enumerate(WEEKS, 1):
        for r in bp.DEMO_AUTHORITIES[w["title"]]:
            yield n, w["title"], r


def test_every_demo_week_has_written_chips_and_nothing_else_does():
    titles = [w["title"] for w in WEEKS]
    assert len(titles) == 9 and set(bp.DEMO_AUTHORITIES) == set(titles)
    OBJ = [DEMO_OBJ_SAMPLE]
    assert all(bp.curated_chips(t, OBJ) for t in titles)
    assert bp.curated_chips(titles[0]) is None      # another course with the same week title keeps the model's chips
    assert bp.curated_chips("Competition law: Art 102 TFEU", [DEMO_OBJ_SAMPLE]) is None


def test_every_case_is_the_triple_name_number_ecli_of_one_source_document():
    docs = [d for d in INDEX["documents"] if d["type"] == "judgment"]
    cases = [(n, r) for n, _, r in _rows() if r["kind"] == "case"]
    assert cases
    for n, r in cases:
        hits = [d for d in docs if d["ecli"] == r["ecli"]]
        assert len(hits) == 1, f"week {n}: {r['chip']} has no source with ECLI {r['ecli']}"
        d = hits[0]
        assert d["case_number"] == r["number"], (r["chip"], d["case_number"])
        assert r["name"].lower().split(" v ")[0].split()[0] in d["title"].lower().replace("-", " ") \
            or r["name"].lower() in d["title"].lower(), (r["chip"], d["title"])
        assert r["number"].replace("Joined Cases ", "").replace("Case ", "").split(" and ")[0] in r["chip"]


def test_every_article_exists_and_is_cited_only_for_its_pairing():
    present = set(INDEX["tfeu_articles_present"])
    arts = [(n, r) for n, _, r in _rows() if r["kind"] == "article"]
    assert arts
    for n, r in arts:
        assert r["treaty"] == "TFEU" and r["article"] in present, r
        why, weeks = PAIRING[r["article"]]
        assert r["for"] == why and n in weeks, (n, r)
        assert r["chip"] == "Art %d TFEU" % r["article"]


def test_chips_carry_no_duplicates_and_stay_under_the_cap():
    for w in WEEKS:
        chips = bp.curated_chips(w["title"], [DEMO_OBJ_SAMPLE])
        assert len(chips) == len(set(chips)) <= bp.MAX_LIST


def _build(reply):
    weeks = [int(w["week"]) for w in WEEKS]
    return bp.normalise_blueprint(reply, syllabus_weeks=weeks, objectives=SEED["brief"]["learning_objectives"].split("\n"),
                                  week_info=bp.weeks_from_block(SYL))


def test_the_model_cannot_change_a_demo_chip():
    a = {"weeks": [{"week": n, "lo": [1], "law": ["Art 260 TFEU", "Art 19 TFEU", "Invented v Case"]} for n in range(1, 10)]}
    b = {"weeks": [{"week": n, "lo": [1], "law": ["Arts 20-21 TFEU"]} for n in range(1, 10)]}
    ta, tb = _build(a)["topics"], _build(b)["topics"]
    assert [t["doctrines"] for t in ta] == [t["doctrines"] for t in tb]
    flat = " ".join(c for t in ta for c in t["doctrines"])
    assert "260" not in flat and "Art 19" not in flat and "Invented" not in flat


def test_every_demo_topic_has_a_doctrine_tag_even_when_the_model_names_none():
    b = _build({"weeks": [{"week": n, "lo": [1], "law": []} for n in range(1, 10)]})
    assert len(b["topics"]) == 9 and all(t["doctrines"] for t in b["topics"])        # M1b


def test_another_course_keeps_what_the_model_named():
    brief = {"syllabus": {"weeks": [{"week": "1", "title": "Competition law: Art 102 TFEU", "topics": ["Dominance"]}]}}
    info = bp.weeks_from_block(cb.syllabus_block(brief))
    b = bp.normalise_blueprint({"weeks": [{"week": 1, "lo": [], "law": ["Art 102 TFEU", "United Brands"]}]},
                               syllabus_weeks=[1], objectives=[], week_info=info)
    assert b["topics"][0]["doctrines"] == ["Art 102 TFEU", "United Brands"]


def test_the_chips_in_a_built_map_are_the_written_ones_in_the_written_order():
    b = _build({"weeks": [{"week": n, "lo": [1], "law": ["x"]} for n in range(1, 10)]})
    by = {t["weeks"][0]: t["doctrines"] for t in b["topics"]}
    assert by[2] == ["Art 34 TFEU", "Dassonville (Case 8/74)", "Cassis de Dijon (Case 120/78)"]
    assert by[1] == ["Art 34 TFEU", "Art 35 TFEU", "Art 36 TFEU"]


# ---- M1: the demo course uses the objectives written for the demo ------------------------------------------
def _md_objectives():
    out, cur = [], None
    for ln in (DEMO / "eu-demo-learning-objectives.md").read_text().split("\n"):
        m = re.match(r"^- \*\*([AB]\d)\.\*\*\s*(.*)$", ln)
        if m:
            cur = [m.group(1), m.group(2)]
            out.append(cur)
        elif ln.startswith("#"):
            cur = None
        elif ln.strip() and cur is not None:
            cur[1] += " " + re.sub(r"^\s*(?:-|\d+\.)\s*", "", ln.strip())
    return [f"{a}. " + re.sub(r"\s+", " ", t.replace("**", "")).strip() for a, t in out]


def test_the_seed_objectives_are_the_thirteen_written_for_the_demo():
    want = _md_objectives()
    assert len(want) == 13 and [w[:2] for w in want] == ["A%d" % i for i in range(1, 9)] + ["B%d" % i for i in range(1, 6)]
    assert SEED["brief"]["learning_objectives"].split("\n") == want
    assert cb.learning_objectives(BRIEF) == want                      # none truncated or renumbered on the way in
    assert "not any university course" in SEED["brief"]["objectives_source"]
    assert "illustrative" in SEED["brief"]["objectives_source"]


FORBIDDEN = re.compile(r"past exam|model answer|exam_prep|mark scheme|ocasys|RGB[A-Z]{2}[0-9]|exam-prep", re.I)


def test_no_demo_file_names_an_exam_source_or_a_rug_course():
    for f in (DEMO / "eu-public-demo-course.json", DEMO / "eu-demo-learning-objectives.md",
              ROOT / "blueprint.py"):
        text = f.read_text()
        assert not FORBIDDEN.search(text), f
        assert not re.search(r"RUG|Groningen", text.replace("University of Groningen course", ""), re.I) or f.suffix == ".md"


def test_demo_text_makes_no_exam_prediction():
    banned = ["exam tests", "what this course examines", "share of the exam", "exam focus", "answer method",
              "exam rewards", "likely to appear", "likely to come up", "will come up", "high-yield", "high yield",
              "examiner", "predict", "assessment focus"]
    blob = json.dumps(SEED).lower() + " ".join(c for _, _, r in _rows() for c in [r["chip"]]).lower()
    assert not [b for b in banned if b in blob]


# ---- the seed's own legal text -------------------------------------------------------------------------------
def _source_text():
    from html.parser import HTMLParser
    class T(HTMLParser):
        def __init__(s):
            super().__init__(convert_charrefs=True); s.o = []
        def handle_data(s, d): s.o.append(d)
    out = []
    for f in sorted((PACK / "sources").glob("*.html")):
        p = T(); p.feed(f.read_text(errors="ignore")); out.append(" ".join(p.o))
    return re.sub(r"\s+", " ", " ".join(out).replace("\xa0", " ")).lower()


@pytest.mark.skipif(not (PACK / "sources").is_dir(), reason="demo source pack not on this machine")
def test_every_quoted_phrase_in_the_seed_cards_is_in_a_source_judgment():
    src = _source_text()
    quoted = re.findall(r'"([^"]{8,})"', " ".join(c["back"] for c in SEED["cards"]))
    assert quoted
    for q in quoted:
        assert q.lower() in src, q


@pytest.mark.skipif(not (PACK / "sources").is_dir(), reason="demo source pack not on this machine")
def test_the_index_matches_the_pack_metadata():
    meta = json.loads((PACK / "metadata.json").read_text())
    want = {d["id"]: (d.get("case_number"), d.get("ecli")) for d in meta["documents"]}
    assert {d["id"]: (d["case_number"], d["ecli"]) for d in INDEX["documents"]} == want
