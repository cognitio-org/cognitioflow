"""The printed pack (Phase 18d) over fixed notes: a page per week (rule box, outline, cases by year with their
note, the method only where it applies) and a tab sheet that carries an article number and one word, nothing more."""
import re

import pack

W3 = {"id": "n3", "title": "Week 3 — Transfer of goods and third-party protection", "body":
      "# Week 3\n\n> **Frame** Classify the system first: causal vs abstract.\n> Then delivery vs consensus.\n\n"
      "## The transfer machine\nSee 3:84 BW and VIII.-2:101 and VIII.-2:101 again.\n\n## Exam hooks and traps\n- trap"}
W1 = {"id": "n1", "title": "Week 1 — Lecture notes: principles and general concepts", "body":
      "> **In one glance** Numerus clausus.\n\n## Principles\nArt 345 TFEU; 3:84 BW; 5:1 BW."}
REF = {"id": "r", "title": "Reference — article index", "body":
       "| Article | Heading | Rule in one line |\n|---|---|---|\n| **3:84** | Basic requirements | title, delivery, power |\n"
       "| VIII.-2:101 | Requirements for the transfer of ownership | five |\n| 5:1 | Ownership | the most complete right |"}
CASES = [{"name": "Gerson v Wilkinson", "cite": "[2001] QB 514", "year": 2001, "notes": [{"id": "n3", "title": W3["title"]}]},
         {"name": "Armory v Delamirie", "cite": "", "year": 1722, "notes": [{"id": "n1", "title": W1["title"]}, {"id": "n3", "title": W3["title"]}]},
         {"name": "Berg/De Bary", "cite": "", "year": None, "notes": [{"id": "n3", "title": W3["title"]}]}]


def _pack(method=False):
    return pack.build({1: [W1], 3: [W3]}, [REF], CASES, method=method)


def test_a_page_per_week_with_its_rule_and_outline():
    t = {x["week"]: x for x in _pack()["topics"]}
    assert list(t) == ["1", "3"]
    assert t["3"]["title"] == "Transfer of goods and third-party protection"
    assert t["3"]["rule"].startswith("**Frame** Classify the system first") and ">" not in t["3"]["rule"]
    assert t["3"]["outline"] == ["The transfer machine", "Exam hooks and traps"]


def test_cases_run_in_the_order_they_were_decided_and_name_their_note():
    cases = {x["week"]: x for x in _pack()["topics"]}["3"]["cases"]
    assert [(c["year"], c["name"]) for c in cases] == [(1722, "Armory v Delamirie"), (2001, "Gerson v Wilkinson"), (None, "Berg/De Bary")]
    assert all(c["note"] == W3["title"] for c in cases)


def test_the_method_prints_only_for_its_course_and_only_where_the_notes_work_it():
    notes = {"id": "e2", "title": "Week 2 — Goods", "body": "Applicability first, then the restriction, then justification."}
    on = pack.build({2: [notes]}, [], [], method=True)["topics"][0]["method"]
    assert on == ["Applicability", "Restriction or scope", "Justification and proportionality"]
    assert pack.build({2: [notes]}, [], [], method=False)["topics"][0]["method"] == []
    assert _pack(method=True)["topics"][1]["method"] == []   # week 3 never works the moves


def test_tabs_are_an_article_and_one_word_from_his_own_index():
    tabs = {t["label"]: t["heading"] for t in _pack()["tabs"]}
    assert tabs["3:84 BW"] == "Requirements" and tabs["VIII.-2:101 DCFR"] == "Requirements" and tabs["5:1 BW"] == "Ownership"
    assert tabs["Art 345 TFEU"] == ""          # not in the index, and week 1's title gives no word: blank, not a guess
    for t in _pack()["tabs"]:                  # nothing that could count as an annotation
        assert re.fullmatch(r"[A-ZÀ-Ý][a-zà-ÿ-]*|", t["heading"]) and len(t["label"].split()) <= 3


def test_tabs_sort_by_instrument_then_number_with_dcfr_books_in_order():
    tabs = pack.build({1: [{"id": "x", "title": "Week 1 — Goods", "body": "IX.-2:101 VIII.-2:101 III.-5:102 3:110 BW 3:84 BW Art 114 TFEU Art 34 TFEU"}]}, [], [])["tabs"]
    assert [t["label"] for t in tabs] == ["Art 34 TFEU", "Art 114 TFEU", "3:84 BW", "3:110 BW", "III.-5:102 DCFR", "VIII.-2:101 DCFR", "IX.-2:101 DCFR"]


def test_the_route_builds_from_the_course_and_never_calls_a_model(client, pg, monkeypatch):
    import run
    monkeypatch.setattr(run, "client", lambda: (_ for _ in ()).throw(AssertionError("no model call")))
    cid = client.post("/api/courses", json={"name": "Pack Law"}).json()["id"]
    client.post(f"/api/courses/{cid}/notes", json={"title": W3["title"], "body": W3["body"] + "\n" + "Rule. " * 300})
    p = client.get(f"/api/courses/{cid}/pack").json()
    assert p["course"] == "Pack Law" and p["topics"][0]["week"] == "3" and any(t["label"] == "3:84 BW" for t in p["tabs"])
    assert client.get("/api/courses/nope/pack").status_code == 404


def test_the_print_page_ships_and_says_it_is_not_for_the_exam():
    import os
    page = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "pack.html")).read()
    assert "never for the exam" in page and "page-break-after:always" in page and 'content="light"' in page
