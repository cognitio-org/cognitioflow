"""Phase 6 — course scaffolding: brief compilation, seeding, course CRUD, delete guard/cascade."""
import io
import json
import logging
import os
import re
import time
import unittest.mock as mock
from pathlib import Path

import psycopg
import pytest

import course_brief as cb

ROOT = Path(__file__).parent.parent


def _pg_url() -> str:
    return os.environ["DATABASE_URL"]


FULL_BRIEF = {
    "course_code": "RGBUBCL001", "period": "Block 1b", "lecturer": "Prof. A. Example", "wg_tutor": "Sam",
    "textbook": "Barendrecht, Constitutional Law 4th ed.", "exam_format": "one essay question and two short problem questions",
    "exam_date": "2027-01-22", "assessment_weighting": "written exam 80%, assignment 20%",
    "permitted_materials": "unannotated Grondwet", "authority_order": ["1. WG notes", "Lecture", "Textbook"],
    "method": "Identify the organ, the power, then the review standard.", "provenance_tags": ["LECTURE", "[WG]"],
    "notes": "Watch the difference between review and scrutiny.",
}


# ---------------------------------------------------------------- compile_prompt: equivalence with the old hand-written prompts

def test_eu_brief_compiles_to_the_original_eu_prompt():
    """Same instructions, same authority order: every line of the original EU_PROMPT survives verbatim;
    the only additions restate BASE_PROMPT's authority hierarchy and provenance tags."""
    import run
    original = (ROOT / "prompts" / "eu_law.md").read_text(encoding="utf-8").strip()
    assert original == run.EU_PROMPT and original.startswith("Course specifics — European Law (Villanueva; WG tutor Phoebe;")
    compiled = cb.compile_prompt(cb.load_seed_brief("eu_law"), "European Law")
    got = compiled.split("\n")

    for line in original.split("\n"):
        assert line in got, f"EU instruction lost: {line[:70]}"
    assert got[0] == original.split("\n")[0]  # header + exam line identical

    extra = [l for l in got if l not in original.split("\n")]
    assert extra == ["AUTHORITY (highest first):", "1. Annotated WG notes", "2. Lecture", "3. Slides", "4. Schütze",
                     "Provenance tags for this course: [LECTURE] [WG] [SLIDES] [READER] [SCHUTZE] [ADDED]"]

    # authority order agrees with the standing hierarchy in BASE_PROMPT (WG notes > lecture slides/transcripts > textbook)
    base = run.BASE_PROMPT
    assert base.index("annotated working-group notes") < base.index("lecture slides/transcripts") < base.index("textbook")
    # provenance tags are exactly the BASE_PROMPT set, same order
    assert re.findall(r"\[[A-Z]+\]", base.split("tag provenance:")[1].split("\n")[0]) == re.findall(r"\[[A-Z]+\]", extra[-1])


def test_property_brief_preserves_every_line_of_property_law_md():
    md = (ROOT / "prompts" / "property_law.md").read_text(encoding="utf-8").split("\n")
    brief = cb.load_seed_brief("property_law")
    compiled = cb.compile_prompt(brief, "Property Law")
    got = compiled.split("\n")
    reshaped = {md[0], md[2]}  # the document title and the "Course: … · Lecturers: … · Textbook: …" line, split into fields
    for line in md:
        if line.strip() and line not in reshaped:
            assert line in got, f"Property Law instruction lost: {line[:70]}"
    for piece in ("Property Law (PL 26/27), University of Groningen", "WG tutor: UNKNOWN — not in project files",
                  brief["lecturer"], brief["textbook"]):
        assert piece in compiled and piece in md[2]
    md_authority = [re.sub(r"^\d+\. ", "", l) for l in md if re.match(r"^\d+\. ", l)][:8]
    assert brief["authority_order"] == md_authority
    # the three owed fields are left for Matej, not invented
    assert brief["exam_format"] == brief["wg_tutor"] == brief["permitted_materials"] == ""
    # the seeded notes say "follow the authority order above" — authority must precede the notes
    assert compiled.index("AUTHORITY (highest first):") < compiled.index("RULES FOR THE TUTOR")


def test_claude_md_course_facts_survive_in_eu_brief():
    b = cb.load_seed_brief("eu_law")
    assert b["authority_order"] == ["Annotated WG notes", "Lecture", "Slides", "Schütze"]
    assert b["provenance_tags"] == ["[LECTURE]", "[WG]", "[SLIDES]", "[READER]", "[SCHUTZE]", "[ADDED]"]
    assert "IRAC" in b["exam_format"] and "Villanueva" == b["lecturer"]


def test_empty_fields_render_nothing():
    assert cb.compile_prompt({}) == ""
    assert cb.brief_is_empty({k: ([] if kind == "list" else "  ") for k, _, kind in cb.BRIEF_FIELDS})
    eu = cb.load_seed_brief("eu_law")
    blanked = dict(eu, course_code="", period="", exam_date="", assessment_weighting="", permitted_materials="")
    assert cb.compile_prompt(blanked, "European Law") == cb.compile_prompt(eu, "European Law")
    assert "Exam date" not in cb.compile_prompt(eu, "European Law")


def test_every_field_renders_when_filled():
    b = cb.normalise_brief(FULL_BRIEF)
    p = cb.compile_prompt(b, "Constitutional Law")
    assert p.split("\n")[0] == ("Course specifics — Constitutional Law (Prof. A. Example; WG tutor Sam; Barendrecht, Constitutional Law 4th ed.). "
                                "Exam: one essay question and two short problem questions.")
    for s in ("Course code: RGBUBCL001 · Period: Block 1b.", "Exam date: 2027-01-22.", "Assessment weighting: written exam 80%, assignment 20%.",
              "Permitted materials in the exam: unannotated Grondwet.", "Identify the organ", "AUTHORITY (highest first):\n1. WG notes\n2. Lecture\n3. Textbook",
              "Provenance tags for this course: [LECTURE] [WG]", "Watch the difference"):
        assert s in p


def test_normalise_brief_validation():
    with pytest.raises(cb.BriefError): cb.normalise_brief({"tutor": "x"})
    with pytest.raises(cb.BriefError): cb.normalise_brief({"exam_date": "22/01/2027"})
    with pytest.raises(cb.BriefError): cb.normalise_brief({"authority_order": "x", "notes": 3})
    assert cb.normalise_brief({"authority_order": "1. WG\n2) Lecture\n\n"})["authority_order"] == ["WG", "Lecture"]


def test_palette_avoids_blackstone_tab_colours():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    tabs = re.findall(r'\["(#[0-9a-f]{6})","[A-Z]', re.search(r"const TABS=\[(.*?)\];", html).group(1))
    assert tabs == cb.TAB_COLOURS
    rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    for c in cb.PALETTE:
        for t in cb.TAB_COLOURS + [cb.BOOK_COVER]:
            assert sum((a - b) ** 2 for a, b in zip(rgb(c), rgb(t))) ** .5 >= 60, (c, t)
    with pytest.raises(cb.BriefError): cb.valid_accent("#2F5FAE")
    assert cb.pick_accent([cb.PALETTE[0]]) == cb.PALETTE[1]


def test_slugs():
    assert cb.slugify("Constitutional Law") == "constitutional-law"
    assert cb.slugify("Schütze & Co.") == "schutze-co"
    assert cb.slugify("!!!") == "course"
    assert cb.unique_slug("eu", {"eu", "eu-2"}) == "eu-3"


# ---------------------------------------------------------------- seeding

def test_seeded_courses_run_on_briefs(client, pg):
    for cid, name, _, seed in cb.SEED_COURSES:
        brief, prompt, slug = pg.execute("SELECT brief, tutor_prompt, slug FROM courses WHERE id=%s", (cid,)).fetchone()
        assert brief == cb.load_seed_brief(seed)
        assert prompt == cb.compile_prompt(brief, name)
        assert slug == cid


def test_legacy_rows_get_seed_brief_once_but_edited_prompts_are_kept(client, pg):
    import run
    pg.execute("UPDATE courses SET brief='{}', tutor_prompt=%s WHERE id='eu'", (run.EU_PROMPT,))
    pg.execute("UPDATE courses SET brief='{}', tutor_prompt='my own prompt' WHERE id='prop'")
    pg.commit()
    run.init()
    eu = pg.execute("SELECT brief, tutor_prompt FROM courses WHERE id='eu'").fetchone()
    prop = pg.execute("SELECT brief, tutor_prompt FROM courses WHERE id='prop'").fetchone()
    assert eu[0] == cb.load_seed_brief("eu_law") and eu[1].startswith(run.EU_PROMPT.split("\n")[0])
    assert prop == ({}, "my own prompt")


# ---------------------------------------------------------------- API

def test_create_course_with_brief(client, pg):
    r = client.post("/api/courses", json={"name": "Constitutional Law", "brief": FULL_BRIEF})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "constitutional-law" and body["accent"] in cb.PALETTE
    row = client.get("/api/courses").json()
    c = next(x for x in row if x["id"] == body["id"])
    assert c["brief"]["exam_date"] == "2027-01-22"
    assert c["tutor_prompt"] == cb.compile_prompt(cb.normalise_brief(FULL_BRIEF), "Constitutional Law")

    again = client.post("/api/courses", json={"name": "Constitutional Law"}).json()
    assert again["slug"] == "constitutional-law-2" and again["accent"] != body["accent"]

    assert client.post("/api/courses", json={"name": "X", "accent": "#d98a2b"}).status_code == 422
    assert client.post("/api/courses", json={"name": "X", "brief": {"exam_date": "soon"}}).status_code == 422
    assert client.post("/api/courses", json={"name": "   "}).status_code == 422


def test_create_course_owned_by_matej_when_user_exists(client, pg):
    pg.execute("INSERT INTO users(id,email,name,created) VALUES('u1',%s,'Matej',0)", (os.environ.get("MATEJ_EMAIL", ""),))
    pg.commit()
    cid = client.post("/api/courses", json={"name": "Tax Law"}).json()["id"]
    assert pg.execute("SELECT user_id FROM courses WHERE id=%s", (cid,)).fetchone()[0] == "u1"


def test_put_brief_recompiles_prompt(client):
    r = client.put("/api/courses/prop", json={"brief": dict(cb.load_seed_brief("property_law"),
                   exam_format="three problem questions", wg_tutor="Tutor T", permitted_materials="statute book")})
    assert r.status_code == 200, r.text
    p = r.json()["tutor_prompt"]
    assert "WG tutor Tutor T" in p and "Exam: three problem questions." in p and "Permitted materials in the exam: statute book." in p
    c = next(x for x in client.get("/api/courses").json() if x["id"] == "prop")
    assert c["tutor_prompt"] == p and c["accent"] == "#2e6b4a"  # partial update leaves the accent alone

    # renaming recompiles the header; brief stays
    p2 = client.put("/api/courses/prop", json={"name": "Property Law II"}).json()["tutor_prompt"]
    assert p2.startswith("Course specifics — Property Law II (") and "Tutor T" in p2


def test_put_empty_brief_keeps_stored_prompt(client):
    cid = client.post("/api/courses", json={"name": "Legacy", "tutor_prompt": "hand-written"}).json()["id"]
    assert client.put(f"/api/courses/{cid}", json={"brief": {}}).json()["tutor_prompt"] == "hand-written"
    pv = client.post("/api/course-brief/preview", json={"name": "Legacy", "brief": {}, "cid": cid}).json()
    assert pv == {"prompt": "hand-written", "fallback": True}


def test_put_slug_conflict(client):
    a = client.post("/api/courses", json={"name": "Alpha"}).json()["id"]
    client.post("/api/courses", json={"name": "Beta"})
    assert client.put(f"/api/courses/{a}", json={"slug": "beta"}).status_code == 409
    assert client.put(f"/api/courses/{a}", json={"slug": "Alpha Two"}).json()["slug"] == "alpha-two"
    assert client.put("/api/courses/nope", json={"name": "x"}).status_code == 404


def test_preview_and_meta(client):
    pv = client.post("/api/course-brief/preview", json={"name": "Constitutional Law", "brief": FULL_BRIEF}).json()
    assert pv["fallback"] is False and "Exam date: 2027-01-22." in pv["prompt"]
    assert client.post("/api/course-brief/preview", json={"brief": {"bogus": 1}}).status_code == 422
    meta = client.get("/api/course-meta").json()
    assert meta["palette"] == cb.PALETTE and [f["key"] for f in meta["fields"]][:3] == ["course_code", "period", "lecturer"]


def test_tutor_system_prompt_contains_compiled_brief_and_is_logged(client, caplog):
    import run
    cid = client.post("/api/courses", json={"name": "Constitutional Law", "brief": FULL_BRIEF}).json()["id"]

    class FakeStream:
        text_stream = iter(["Which organ holds the power?"])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with caplog.at_level(logging.DEBUG, logger="cognitioflow"), mock.patch.object(run, "client", return_value=fake):
        r = client.post(f"/api/courses/{cid}/chat", json={"message": "drill me", "mode": "drill"})
    assert r.status_code == 200 and "[DONE]" in r.text
    compiled = cb.compile_prompt(cb.normalise_brief(FULL_BRIEF), "Constitutional Law")
    sent = fake.messages.stream.call_args.kwargs["system"][0]["text"]
    assert compiled in sent and sent.startswith(run.BASE_PROMPT) and sent.endswith(run.MODES["drill"])
    logged = [rec.getMessage() for rec in caplog.records if rec.name == "cognitioflow" and rec.levelno == logging.DEBUG]
    assert any(compiled in m for m in logged)
    assert not any("sk-ant" in m for m in logged)


# ---------------------------------------------------------------- delete guard + cascade

def _counts(pg, cid):
    q = lambda sql: pg.execute(sql, (cid,)).fetchone()[0]
    return {
        "courses": q("SELECT COUNT(*) FROM courses WHERE id=%s"),
        "files": q("SELECT COUNT(*) FROM files WHERE course_id=%s"),
        "messages": q("SELECT COUNT(*) FROM messages WHERE course_id=%s"),
        "notes": q("SELECT COUNT(*) FROM notes WHERE course_id=%s"),
        "cards": q("SELECT COUNT(*) FROM cards WHERE course_id=%s"),
        "sessions": q("SELECT COUNT(*) FROM sessions WHERE course_id=%s"),
        "reviews": q("SELECT COUNT(*) FROM reviews WHERE card_id IN (SELECT id FROM cards WHERE course_id=%s)"),
        "note_versions": q("SELECT COUNT(*) FROM note_versions WHERE note_id IN (SELECT id FROM notes WHERE course_id=%s)"),
        "recordings": q("SELECT COUNT(*) FROM recordings WHERE note_id IN (SELECT id FROM notes WHERE course_id=%s)"),
    }


def _orphans(pg):
    """Rows whose parent no longer exists, across every course-keyed table."""
    q = lambda sql: pg.execute(sql).fetchone()[0]
    return {
        "files": q("SELECT COUNT(*) FROM files WHERE course_id NOT IN (SELECT id FROM courses)"),
        "messages": q("SELECT COUNT(*) FROM messages WHERE course_id NOT IN (SELECT id FROM courses)"),
        "notes": q("SELECT COUNT(*) FROM notes WHERE course_id NOT IN (SELECT id FROM courses)"),
        "cards": q("SELECT COUNT(*) FROM cards WHERE course_id NOT IN (SELECT id FROM courses)"),
        "sessions": q("SELECT COUNT(*) FROM sessions WHERE course_id NOT IN (SELECT id FROM courses)"),
        "reviews": q("SELECT COUNT(*) FROM reviews WHERE card_id NOT IN (SELECT id FROM cards)"),
        "note_versions": q("SELECT COUNT(*) FROM note_versions WHERE note_id NOT IN (SELECT id FROM notes)"),
        "recordings": q("SELECT COUNT(*) FROM recordings WHERE note_id NOT IN (SELECT id FROM notes)"),
    }


def _fill(client, pg, cid):
    client.post(f"/api/courses/{cid}/files", files={"file": ("w1.txt", io.BytesIO(b"Art 1 Grondwet"), "text/plain")}, data={"week": "1"})
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "N", "body": "b"}).json()["id"]
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "Q", "back": "A"}).json()["id"]
    client.post(f"/api/cards/{kid}/review", json={"rating": 2})
    client.post(f"/api/notes/{nid}/recordings/start")
    client.post(f"/api/courses/{cid}/sessions", json={"day": "2026-09-15", "topic": "t", "minutes": 30})
    pg.execute("INSERT INTO note_versions VALUES(%s,%s,'N','old',%s)", ("v-" + cid, nid, time.time()))
    pg.execute("INSERT INTO messages VALUES(%s,%s,'user','hi',%s)", ("m-" + cid, cid, time.time()))
    pg.commit()


def test_delete_guard_then_force_cascades_without_orphans(client, pg):
    cid = client.post("/api/courses", json={"name": "Doomed"}).json()["id"]
    _fill(client, pg, cid)
    _fill(client, pg, "eu")  # a neighbour that must be untouched
    before = _counts(pg, cid)
    assert all(v >= 1 for v in before.values()), before
    eu_before = _counts(pg, "eu")
    stored = pg.execute("SELECT path FROM files WHERE course_id=%s", (cid,)).fetchone()[0]
    assert Path(stored).exists()

    assert client.get(f"/api/courses/{cid}/usage").json() == {"files": 1, "notes": 1, "cards": 1, "messages": 1, "sessions": 1}
    r = client.delete(f"/api/courses/{cid}")
    assert r.status_code == 409 and "1 file(s), 1 note(s) and 1 card(s)" in r.json()["detail"]
    assert _counts(pg, cid) == before  # guard changed nothing

    r = client.delete(f"/api/courses/{cid}?force=1")
    assert r.status_code == 200, r.text
    assert _counts(pg, cid) == {k: 0 for k in before}
    assert _orphans(pg) == {k: 0 for k in _orphans(pg)}
    assert _counts(pg, "eu") == eu_before
    assert not Path(stored).exists()
    assert client.delete(f"/api/courses/{cid}").status_code == 404


def test_delete_empty_course_needs_no_force_but_last_course_is_kept(client, pg):
    cid = client.post("/api/courses", json={"name": "Empty"}).json()["id"]
    assert client.delete(f"/api/courses/{cid}").status_code == 200
    assert client.delete("/api/courses/prop?force=1").status_code == 200
    r = client.delete("/api/courses/eu?force=1")
    assert r.status_code == 409 and "only course" in r.json()["detail"]
    assert pg.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 1
