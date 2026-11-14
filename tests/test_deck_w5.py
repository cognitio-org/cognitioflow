"""One-click deck (definition-of-8/deck.md, wave 5): the pure card rules, the honest result line, and the build-all
route against a stubbed model. The route tests need the protected run.py patch (docs/pending-protected/deck-build-all.patch)
and skip themselves without it; the rest runs on every head."""
import io
import json
import time
import types

import pytest

import concepts
import run

NEEDS_PATCH = pytest.mark.skipif(not hasattr(run, "DECK_BUDGET_S"), reason="needs docs/pending-protected/deck-build-all.patch")


# ---------------------------------------------------------------- pure: clean items (Must 10)
CON = {"name": "Dassonville formula", "statement": "Any trading rule capable of hindering trade is an MEQR under Article 30 of the EEC Treaty.",
       "authority": "Dassonville, Case 8/74", "limbs": [], "traps": []}


def test_clean_cards_drops_echo_markdown_test_text_and_empty():
    payload = {"cards": [
        {"front": "What is the Dassonville formula?", "back": "Any trading rule capable of hindering trade (Dassonville, Case 8/74)."},
        {"front": "What is the Dassonville formula for trade?", "back": "What is the Dassonville formula for trade?"},   # echo
        {"front": "Testcase Number0 about the formula", "back": "An answer that is long enough to count."},            # test text
        {"front": "```json {\"a\": 1} ```", "back": "An answer that is long enough to count."},                      # raw markdown
        {"front": "Short?", "back": ""},                                                                            # empty
    ]}
    kept, why = concepts.clean_cards(payload, CON)
    assert [c["front"] for c in kept] == ["What is the Dassonville formula?"]
    assert len(why) == 4


def test_clean_cards_strips_emphasis_and_adds_the_authority_when_the_answer_names_none():
    kept, _ = concepts.clean_cards({"cards": [{"front": "**What** is the formula?", "back": "Any rule that can hinder trade."}]}, CON)
    assert kept[0]["front"] == "What is the formula?"
    assert kept[0]["back"].endswith("(Dassonville, Case 8/74)")
    kept, _ = concepts.clean_cards({"cards": [{"front": "What is the formula?", "back": "Rules that hinder trade, Article 30 of the EEC Treaty."}]}, CON)
    assert "Case 8/74" not in kept[0]["back"]   # it already names its article


def test_near_duplicate_fronts_and_exact_duplicates_are_found():
    assert concepts.dup_of("What does the Dassonville formula cover?", ["What does the Dassonville formula cover?"])
    assert concepts.dup_of("Dassonville formula covers which trading rules hindering intra-Community trade directly indirectly actually potentially?", ["Dassonville formula covers which trading rules hindering intra-Community trade directly indirectly actually potentially today?"])
    assert not concepts.dup_of("What are the limbs of the Keck test?", ["What does the Dassonville formula cover?"])


def test_an_article_may_not_change_its_treaty():
    assert concepts.citations_ok("Article 30 EEC prohibits it.", CON)
    assert not concepts.citations_ok("Article 30 TFEU prohibits it.", CON)      # 30 TFEU is customs duties
    assert not concepts.citations_ok("Directive 2021/100 applies.", CON)        # a directive the concept never carried


def test_a_quote_survives_curly_quotes_and_dashes():
    assert concepts.grounded("the law stemming from the treaty — an independent source of law",
                             "x The law stemming from the Treaty, an independent source of law y")


# ---------------------------------------------------------------- pure: the result line (Must 3)
def test_the_line_never_says_built_alone():
    clean = concepts.deck_line(built={"1": (3, 1)}, deck_cards=3, deck_problems=1)
    assert clean.startswith("Built (") and "left" not in clean and "skipped" not in clean
    assert concepts.deck_line(built={}, deck_cards=0, deck_problems=0).startswith("Built nothing.")
    messy = concepts.deck_line(built={"1": (3, 1)}, deck_cards=3, deck_problems=1, skipped=["A: the reply was not JSON", "B: the reply was not JSON"],
                               pending_concepts=4, failed_weeks=["week 2 produced no concepts"])
    assert messy.startswith("Partly built")
    assert "2 skipped: the reply was not JSON (2)" in messy
    assert "4 concepts left, press again to build them" in messy
    assert "Failed: week 2 produced no concepts" in messy
    assert "Built (" not in messy


# ---------------------------------------------------------------- build-all against a stubbed model
def _cid(client):
    return client.post("/api/courses", json={"name": "Deck w5 test"}).json()["id"]


def _upload(client, cid, name, text, week):
    r = client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(text.encode()), "text/plain")}, data={"week": week})
    assert r.status_code == 200
    return r.json()["id"]


def _msg(text):
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], model="fake-cheap")


SRC_A = ("Dassonville (Case 8/74): all trading rules enacted by Member States which are capable of hindering, directly or "
         "indirectly, actually or potentially, intra-Community trade are to be considered as measures having an effect equivalent "
         "to quantitative restrictions. A second sentence that is quoted by the dropped concept is not here at all.")
SRC_B = "Van Gend en Loos (Case 26/62): the Community constitutes a new legal order of international law for the benefit of which the States have limited their sovereign rights."


def _stub(monkeypatch, delay=0.0, fail_week_b=True):
    concept_a = {"concepts": [
        {"name": "Dassonville formula", "kind": "test", "statement": "A trading rule capable of hindering trade is an MEQR.",
         "limbs": ["a trading rule"], "traps": [], "authority": "Dassonville, Case 8/74", "method_tag": "free movement",
         "quote": "all trading rules enacted by Member States which are capable of hindering"},
        {"name": "Second concept", "kind": "rule", "statement": "A rule about something else entirely.", "authority": "Dassonville, Case 8/74",
         "quote": "this sentence is not in the material at all, it was invented by the model"},      # dropped: quote not found
        {"name": "Third concept", "kind": "rule", "statement": "A third rule from the same source.", "authority": "Dassonville, Case 8/74",
         "quote": "capable of hindering, directly or indirectly, actually or potentially"},
        {"name": "Fourth concept", "kind": "rule", "statement": "A fourth rule from the same source.", "authority": "Dassonville, Case 8/74",
         "quote": "intra-Community trade are to be considered as measures having an effect equivalent"},
    ]}
    seen = {"n": 0}

    def fake_ask(model, *a, **k):
        if k.get("system") == concepts.EXTRACT_RULES:
            material = k["messages"][0]["content"]
            if "Van Gend" in material:
                return _msg("this is not json at all" if fail_week_b else json.dumps({"concepts": []}))
            return _msg(json.dumps(concept_a))
        time.sleep(delay)
        seen["n"] += 1
        brief = json.loads(k["messages"][0]["content"])
        name = brief["concept"]
        return _msg(json.dumps({"cards": [{"front": f"What does the {name} say about trade?",
                                           "back": f"{name}: a rule from Dassonville, Case 8/74, about hindering trade."}]}))
    monkeypatch.setattr(run, "ask_model", fake_ask)
    return seen


def _counts(cid):
    c = run.rows("SELECT COALESCE(week,'') AS w, COUNT(*) AS n FROM cards WHERE course_id=? GROUP BY 1", cid)
    q = run.rows("SELECT COALESCE(week,'') AS w, COUNT(*) AS n FROM essay_questions WHERE course_id=? AND kind='problem' GROUP BY 1", cid)
    return {r["w"]: r["n"] for r in c}, {r["w"]: r["n"] for r in q}


@NEEDS_PATCH
def test_result_line_tells_the_truth_about_dropped_failed_and_pending(client, monkeypatch):
    cid = _cid(client)
    _upload(client, cid, "dassonville-8-74.txt", SRC_A, "1")
    _upload(client, cid, "van-gend-26-62.txt", SRC_B, "2")
    _stub(monkeypatch, delay=0.25)
    monkeypatch.setattr(run, "DECK_WORKERS", 1)
    monkeypatch.setattr(run, "DECK_BUDGET_S", 0.4)     # one concept is written, the rest are left
    r = client.post(f"/api/courses/{cid}/concepts/build-all")
    assert r.status_code == 200
    d = r.json()
    cards, problems = _counts(cid)
    # the numbers on the line are the numbers that exist (API/DB count), not an estimate
    assert d["deck"]["cards"] == sum(cards.values()) and d["deck"]["problems"] == sum(problems.values())
    assert f"Deck now: {sum(cards.values())} cards, {sum(problems.values())} problems." in d["line"]
    assert d["line"].startswith(("Partly built", "Built nothing"))
    assert "Built (" not in d["line"]
    assert "skipped" in d["line"] and "its quote is not in the material" in d["line"]          # the dropped concept and why
    assert "Failed: week 2 produced no concepts" in d["line"]                                  # the failed week
    assert d["pending"]["concepts"] >= 1
    assert f"{d['pending']['concepts']} concept" in d["line"] and "left, press again to build them" in d["line"]
    assert d["label"] == concepts.AI_LABEL


@NEEDS_PATCH
def test_second_click_builds_only_what_is_pending_and_adds_no_duplicates(client, monkeypatch):
    cid = _cid(client)
    _upload(client, cid, "dassonville-8-74.txt", SRC_A, "1")
    seen = _stub(monkeypatch, delay=0.25, fail_week_b=False)
    monkeypatch.setattr(run, "DECK_WORKERS", 1)
    monkeypatch.setattr(run, "DECK_BUDGET_S", 0.4)
    first = client.post(f"/api/courses/{cid}/concepts/build-all").json()
    assert first["pending"]["concepts"] >= 1
    before, _ = _counts(cid)
    monkeypatch.setattr(run, "DECK_BUDGET_S", 100.0)
    second = client.post(f"/api/courses/{cid}/concepts/build-all").json()
    assert second["pending"] == {"concepts": 0, "files": 0}
    assert second["totals"]["concepts"] == 0                  # the file was read once; it is never re-asked
    fronts = [r["front"] for r in run.rows("SELECT front FROM cards WHERE course_id=?", cid)]
    assert len(fronts) == len(set(fronts)), "a front was written twice"
    third = client.post(f"/api/courses/{cid}/concepts/build-all").json()
    assert third["nothing_new"] is True and third["line"].startswith("Nothing new to build")
    assert third["totals"]["cards"] == 0
    after, _ = _counts(cid)
    assert sum(after.values()) >= sum(before.values())


@NEEDS_PATCH
def test_a_run_that_builds_nothing_never_says_built_alone(client, monkeypatch):
    cid = _cid(client)
    _upload(client, cid, "van-gend-26-62.txt", SRC_B, "2")
    _stub(monkeypatch)
    d = client.post(f"/api/courses/{cid}/concepts/build-all").json()
    assert d["line"].startswith("Built nothing.")
    assert "Failed: week 2" in d["line"]


@NEEDS_PATCH
def test_a_source_too_long_to_read_whole_is_said_not_silently_cut(client, monkeypatch):
    cid = _cid(client)
    _upload(client, cid, "tfeu.txt", ("Article 34 TFEU prohibits quantitative restrictions. " * 5000), "1")
    monkeypatch.setattr(run, "DECK_FILE_MAX", 1000)
    _stub(monkeypatch)
    d = client.post(f"/api/courses/{cid}/concepts/build-all").json()
    assert "too long to read as one source" in d["line"]


# ---------------------------------------------------------------- Recall is scoped to the course (Must 4)
def test_a_second_courses_due_cards_never_reach_this_courses_recall(client):
    a, b = _cid(client), _cid(client)
    for i in range(3):
        client.post(f"/api/courses/{a}/cards", json={"front": f"Course A question number {i}?", "back": "Course A answer", "source": "x", "week": "1"})
    for i in range(5):
        client.post(f"/api/courses/{b}/cards", json={"front": f"Course B private question {i}?", "back": "Course B answer", "source": "x", "week": "1"})
    due_a = client.get(f"/api/courses/{a}/cards?due=1").json()
    assert len(due_a) == 3 and all("Course A" in c["front"] for c in due_a)
    assert not any("Course B" in c["front"] for c in due_a)
    assert client.get(f"/api/courses/{a}/cards?due=1&week=1").json() == due_a
    assert client.get(f"/api/courses/{a}/stats").json()["due"] == 3


def test_the_recall_page_has_a_plain_empty_state_and_the_label():
    import pathlib
    root = pathlib.Path(run.__file__).parent / "static"
    js, html = (root / "app.js").read_text(), (root / "index.html").read_text()
    assert "No cards in this course yet" in js and "No cards are due" in js
    assert 'id="fc" tabindex="0" aria-label="Flashcard — click to flip" hidden' in html     # never an empty Question box before the load
    assert "AI-generated from your course files. Verify against your materials." in html
    assert "AI-generated from your course files. Verify against your materials." in js
    assert concepts.AI_LABEL == "AI-generated from your course files. Verify against your materials."
