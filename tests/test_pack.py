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


# ---------------------------------------------------------------- the table normaliser and tidying (pitch freeze)
def _n(name, cite="", year=None, note="a"):
    return {"name": name, "cite": cite, "year": year, "notes": [{"id": note, "title": note}]}


def test_the_same_case_under_two_spellings_is_one_row_with_the_written_year():
    out = pack.normalise_cases([_n("Van Gend & Loos", "C-26/62", 1962), _n("Van Gend en Loos", "[1963] ECR 1", 1963, "b"),
                                _n("Costa v ENEL", "[1964] ECR 585", 1964), _n("Costa/ENEL", "6/64", 1964, "b")])
    assert [(c["name"], c["cite"], c["year"]) for c in out] == [("Van Gend en Loos", "Case 26/62, [1963] ECR 1", 1963),
                                                                 ("Costa v ENEL", "Case 6/64, [1964] ECR 585", 1964)]
    assert {x["id"] for x in out[0]["notes"]} == {"a", "b"}


def test_case_numbers_take_one_style_and_reports_are_left_alone():
    out = pack.normalise_cases([_n("Dassonville", "8/74"), _n("Francovich", "C-6/90"), _n("Keck and Mithouard", "C-267/91 & C-268/91"),
                                _n("Sison", "T-47/03"), _n("Gerson v Wilkinson", "[2001] QB 514", 2001), _n("Kadi", "ECLI:EU:C:2008:461")])
    assert [c["cite"] for c in out] == ["Case 8/74", "Case C-6/90", "Joined Cases C-267/91 & C-268/91", "Case T-47/03", "[2001] QB 514", "ECLI:EU:C:2008:461"]
    assert out[-1]["year"] == 2008 and out[0]["year"] == 1974


def test_doctrines_and_doubled_years_and_merged_rows():
    out = pack.normalise_cases([_n("Direct effect", "93/71", 1971), _n("Proportionality"), _n("United Brands [1978]", "[1978]", 1978),
                                _n("Francovich; Brasserie du Pecheur", "C-6/90; C-46/93", 1990)])
    assert [(c["name"], c["cite"], c["year"]) for c in out] == [("United Brands", "", 1978), ("Francovich", "Case C-6/90", 1990),
                                                                 ("Brasserie du Pecheur", "Case C-46/93", 1993)]


def test_the_normaliser_does_not_over_merge_or_over_split():
    out = pack.normalise_cases([_n("Simmenthal", "106/77"), _n("Simmenthal II", "92/78"), _n("Costa/ENEL", "6/64"),
                                _n("Berg/De Bary"), _n("Keck", "C-267/91"), _n("Keck and Mithouard", "C-267/91 & C-268/91"),
                                _n("A; B; C", "C-1/90; C-2/90"), _n("Direct effect of directives")])
    names = [c["name"] for c in out]
    assert names == ["Simmenthal", "Simmenthal II", "Costa/ENEL", "Berg/De Bary", "Keck and Mithouard", "A; B; C", "Direct effect of directives"]
    assert [c for c in out if c["name"] == "A; B; C"][0]["cite"] == "Joined Cases C-1/90 & C-2/90"   # counts differ: not split, cite kept


def test_a_case_from_an_earlier_week_reprints_only_where_the_week_works_it():
    w1 = {"id": "w1", "title": "Week 1 — Direct effect", "body": "*Van Gend en Loos* and *Cassis de Dijon*."}
    w2 = {"id": "w2", "title": "Week 2 — Goods", "body": "As in *Van Gend en Loos*, rights arise. *Cassis de Dijon* again; Cassis is the test."}
    cases = [_n("Van Gend en Loos", "26/62", 1963, "w1"), _n("Cassis de Dijon", "120/78", 1979, "w1")]
    for c in cases: c["notes"].append({"id": "w2", "title": w2["title"]})
    t = {x["week"]: x for x in pack.build({1: [w1], 2: [w2]}, [], cases)["topics"]}
    assert [c["name"] for c in t["1"]["cases"]] == ["Van Gend en Loos", "Cassis de Dijon"]
    assert [c["name"] for c in t["2"]["cases"]] == ["Cassis de Dijon"] and t["2"]["recalled"] == ["Van Gend en Loos"]


def test_titles_and_outlines_are_calm_deduped_and_free_of_wg_answers():
    body = ("## LECTURE 3A: FREE MOVEMENT OF GOODS — NEGATIVE INTEGRATION\n## IRAC STRUCTURE\n## WG 2 answers — Q1\n## Q2\n"
            "## In one glance\n## Case map\n## 1 Treaty Framework\n## IRAC structure\n## Scope\n## Scope (Lecture 1 & 2, 31 Aug)\n")
    wg = {"id": "g", "title": "WG 2 — answers", "body": "## Next Gen Pharmacy v German Association\n## PRELIMINARY QUESTION"}
    t = pack.build({2: [{"id": "x", "title": "WEEK 2 EU LAW COMPLETE LECTURE NOTES", "body": body}, wg]}, [], [])["topics"][0]
    assert t["title"] == "Free movement of goods — negative integration"
    # the Lecture 3A line only repeats the title, and "IRAC structure" is an answer's scaffolding
    assert t["outline"] == ["Treaty Framework", "Scope"]
    assert pack._tidy_title("Week 1 — Foundations: the EU legal order") == "Foundations: the EU legal order"


def test_tabs_drop_articles_that_do_not_exist_and_name_the_ones_that_do():
    tabs = {t["label"]: t["heading"] for t in pack.build({1: [{"id": "x", "title": "Week 1 — Basics",
            "body": "Art 168 TEU; Art 34 TFEU; Art 2 TEU; Art 400 TFEU; Art 60 Charter; Art 47 Charter"}]}, [], [])["tabs"]}
    assert "Art 168 TEU" not in tabs and "Art 400 TFEU" not in tabs and "Art 60 Charter" not in tabs
    # the proposed article subjects stay off until Matej says yes: the week's title word, as signed off
    assert tabs["Art 34 TFEU"] == tabs["Art 2 TEU"] == tabs["Art 47 Charter"] == "Basics"


def test_the_print_page_carries_the_ai_label_on_every_printed_section():
    import os
    page = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "pack.html")).read()
    assert "data-ai-label>AI-generated" in page and page.count("${ai}") == 2   # end of each week page and of the tab sheet
    assert "position:fixed" not in page          # in flow, so it never masks a row on a full A4 page


def test_wg_answers_stay_out_even_inside_a_lecture_note_and_a_wg_only_week_still_prints():
    body = "## Free movement\n# WG 2 answers\n## Next Gen Pharmacy v German Association\n## IRAC structure\n# Lecture 4\n## Services"
    t = pack.build({2: [{"id": "x", "title": "Week 2 — Goods", "body": body}]}, [], [])["topics"][0]
    assert t["outline"] == ["Free movement", "Services"]
    only = pack.build({5: [{"id": "g", "title": "WG 5 — answers", "body": "> **In one glance** Set question.\n## Damages"}]}, [], [])["topics"][0]
    assert only["rule"] and only["outline"] == ["Damages"]


def test_titles_keep_a_capital_and_years_do_not_depend_on_row_order():
    assert pack._tidy_title("Week 1 — Lecture notes: principles and general concepts") == "Principles and general concepts"
    a, b = _n("Van Gend & Loos", "C-26/62", 1962), _n("Van Gend en Loos", "", 1963, "b")   # 1963 from a Year column
    assert pack.normalise_cases([a, b])[0]["year"] == 1963 and pack.normalise_cases([b, a])[0]["year"] == 1963


def test_a_case_named_by_its_short_form_is_still_worked_in_a_later_week():
    w1 = {"id": "w1", "title": "Week 1 — Goods", "body": "*Keck and Mithouard*"}
    w2 = {"id": "w2", "title": "Week 2 — Selling", "body": "*Keck and Mithouard* again. Keck narrows it; after Keck, selling arrangements."}
    c = _n("Keck and Mithouard", "C-267/91", 1993, "w1"); c["notes"].append({"id": "w2", "title": w2["title"]})
    t = {x["week"]: x for x in pack.build({1: [w1], 2: [w2]}, [], [c])["topics"]}
    assert [x["name"] for x in t["2"]["cases"]] == ["Keck and Mithouard"] and t["2"]["recalled"] == []


# ---------------------------------------------------------------- follow-up to #224 (skeptic + judge findings)
def test_an_opinion_is_never_turned_into_a_case_number():
    for name in ("*Opinion 2/13*", "Opinion 2/13", "Opinion 1/09", "Opinion 2/94"):
        out = pack.normalise_cases([_n(name, "", 2000 + int(name.strip("*")[-2:]) if name.strip("*")[-2:] < "50" else 1994)])
        assert [(c["name"], c["cite"], c["year"]) for c in out] == [(name.strip("*"), "", None)]   # no 'Case C-2/13', no year read off it
    out = pack.normalise_cases([_n("Opinion 2/13", "Opinion 2/13, EU:C:2014:2454")])
    assert out[0]["name"] == "Opinion 2/13" and "Case" not in out[0]["cite"]


def test_one_cite_for_several_names_keeps_one_row_with_its_cite_and_year():
    out = pack.normalise_cases([_n("Brasserie du Pêcheur; Factortame III", "C-46/93 & C-48/93", 1996)])
    assert [(c["name"], c["cite"], c["year"]) for c in out] == [("Brasserie du Pêcheur; Factortame III", "Joined Cases C-46/93 & C-48/93", 1996)]
    out = pack.normalise_cases([_n("Brasserie du Pêcheur; Factortame III", "C-46/93 & C-48/93", 1993)])
    assert out[0]["cite"] and out[0]["year"] == 1993 and out[0]["numbered"]     # 1993 is the number's year, flagged


def test_a_page_number_is_never_a_year():
    out = pack.normalise_cases([_n("Costa v ENEL", "Case 6/64, ECR 1585", 1964)])
    assert out[0]["year"] == 1964 and out[0]["cite"] == "Case 6/64, ECR 1585"
    assert pack.normalise_cases([_n("Costa v ENEL", "Case 6/64, [1964] ECR 585")])[0]["year"] == 1964


def test_only_cjeu_numbers_are_restyled_and_suffixes_and_letters_are_kept_as_written():
    out = pack.normalise_cases([_n("Tyrer v UK", "5856/72", 1972), _n("Kadi", "C-402/05 P"), _n("Francovich", "6/90"),
                                _n("Commission v World Duty Free Group", "Joined Cases C-20/15 P and C-21/15 P"),
                                _n("Ireland and Others v Commission (Apple)", "Joined Cases T-778/16 and T-892/16"), _n("Lorenz", "Case 120/73")])
    got = {c["name"]: (c["cite"], c["year"]) for c in out}
    assert got["Tyrer v UK"] == ("5856/72", None)                      # an ECtHR application number, left alone and undated
    assert got["Kadi"] == ("Case C-402/05 P", 2005)
    assert got["Francovich"] == ("Case 6/90", 1990)                   # no 'C-' added to a number written without one
    assert got["Commission v World Duty Free Group"][0] == "Joined Cases C-20/15 P & C-21/15 P"
    assert got["Ireland and Others v Commission (Apple)"][0] == "Joined Cases T-778/16 & T-892/16"
    assert got["Lorenz"] == ("Case 120/73", 1973)
    assert pack.normalise_cases([_n("Kadi", "C-402/05"), _n("Kadi", "C-402/05 P", note="b")])[0]["cite"] == "Case C-402/05 P"


def test_the_year_column_says_which_years_are_read_off_a_case_number():
    out = {c["name"]: c for c in pack.normalise_cases([_n("Cassis de Dijon", "120/78", 1978), _n("Van Gend en Loos", "[1963] ECR 1", 1962),
                                                       _n("Gerson v Wilkinson", "[2001] QB 514", 2001), _n("Francovich (1991)", "C-6/90")])}
    assert out["Cassis de Dijon"]["numbered"] and out["Cassis de Dijon"]["year"] == 1978
    assert not out["Van Gend en Loos"]["numbered"] and out["Van Gend en Loos"]["year"] == 1963
    assert not out["Gerson v Wilkinson"]["numbered"]
    assert out["Francovich"]["year"] == 1991 and not out["Francovich"]["numbered"]   # a year the notes wrote beside the name
    import os
    page = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "pack.html")).read()
    assert "in the order they were decided" not in page and "numbered" in page


def test_proposed_tab_words_are_off_and_single_words():
    assert pack._HEADINGS == {}
    assert all(re.fullmatch(r"[A-Z][a-z]+", w) for w in pack._HEADINGS_PROPOSED.values())
    tabs = pack.build({1: [{"id": "x", "title": "Week 1 — Lecture notes", "body": "Art 34 TFEU"}]}, [], [])["tabs"]
    assert tabs[0]["heading"] == ""                                     # no word to be had: blank, not a guess


def test_a_tutorial_titled_doctrine_note_is_not_demoted_and_unlabelled_answers_stay_out():
    doc = {"id": "d", "title": "Tutorial notes — state aid", "body": "> **In one glance** Art 107(1) TFEU, four criteria.\n## Selectivity\n## Recovery"}
    other = {"id": "o", "title": "Week 5 — Competition", "body": "## Undertakings"}
    t = pack.build({5: [doc, other]}, [], [])["topics"][0]
    assert "Selectivity" in t["outline"] and t["rule"].startswith("**In one glance** Art 107")
    body = ("## Selectivity\n## Next Gen Pharmacy v German Association of Pharmacists\nFacts.\n## Preliminary question — goods or services?\n"
            "## IRAC structure\n## Quick reference card\n## Advice to the client\n## Recovery\n[WG] answer\n## Commission v Italy\nThe case.")
    cases = [_n("Commission v Italy", "C-576/18", note="x")]
    t = pack.build({5: [{"id": "x", "title": "Week 5 — State aid", "body": body}]}, [], cases)["topics"][0]
    assert t["outline"] == ["Selectivity", "Commission v Italy"]       # a heading naming a real indexed case stays


def test_the_from_column_names_a_week_once():
    t = pack.build({2: [{"id": "x", "title": "WEEK 2 EU LAW COMPLETE LECTURE NOTES",
                         "body": "## Lecture 3A: Free movement of goods\n*Dassonville* 8/74"}]}, [], [_n("Dassonville", "8/74", 1974, "x")])["topics"][0]
    assert t["title"] == "Free movement of goods" and t["outline"] == []
    assert t["cases"][0]["note"] == "Week 2 lecture notes — Free movement of goods"
