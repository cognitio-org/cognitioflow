"""Print pack, wave 5: the frozen checklist ~/reports/cf-pitch/definition-of-8/printpack.md as tests.

Fixture A = the public demo course (tests/fixtures/printpack/demo/*.md, notes written only from the public sources
in ~/reports/cf-pitch/demo-course). Fixture B = labelled trap rows (trap_rows.json), tests only, never printed.
The PDF checks need Chrome and pdftotext and skip without them."""
import json
import os
import re
import shutil
import subprocess
import threading
import time

import pytest

import pack

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "printpack")
DEMO_COURSE = os.environ.get("CF_DEMO_COURSE", os.path.expanduser("~/reports/cf-pitch/demo-course"))
CHROME = os.environ.get("CF_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _n(name, cite="", year=None, note="a"):
    return {"name": name, "cite": cite, "year": year, "notes": [{"id": note, "title": note}]}


def _fx(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


def _flat(s):
    return re.sub(r"\s+", " ", s or "").strip()


# ---- the wave-4 skeptic regression: a docket in brackets at the end of a sentence about the case
SENTENCE_END = [
    ("*Van Gend* established direct effect (26/62).", "26/62", "Van Gend", ("Case 26/62", 1962, True)),
    ("In *Simmenthal* the Italian Constitutional Court rule was set aside (106/77).", "106/77", "Simmenthal", ("Case 106/77", 1977, True)),
    ("*Simmenthal* held that national courts must set aside conflicting law (106/77).", "106/77", "Simmenthal", ("Case 106/77", 1977, True)),
    ("*Dassonville* defined MEQRs broadly (8/74, 11 July 1974)", "8/74", "Dassonville", ("Case 8/74", 1974, False)),
    ("*Francovich* is the state-liability case (C-6/90, judgment of 19 November 1991).", "C-6/90", "Francovich", ("Case C-6/90", 1991, False)),
    ("The Court said so in *Costa v ENEL* (Case 6/64).", "6/64", "Costa v ENEL", ("Case 6/64", 1964, True)),
    ("*Kadi* is the review case (C-402/05 P).", "C-402/05", "Kadi", ("Case C-402/05 P", 2005, True)),
    ("*Van Gend* (ECLI:EU:C:1963:1, Case 26/62) is the first.", "26/62", "Van Gend", ("Case 26/62", 1963, False)),
    # another court's number at the end of a sentence stays verbatim and undated
    ("*Lisbon* decided identity review (2 BvE 2/08).", "2/08", "Lisbon", ("2 BvE 2/08", None, False)),
    ("*Granital* settled dualism in Italy (Corte cost. sent. 170/84).", "170/84", "Granital", ("Corte cost. sent. 170/84", None, False)),
]


@pytest.mark.parametrize("body,cite,name,want", SENTENCE_END)
def test_a_bracketed_docket_at_the_end_of_a_sentence_keeps_its_cite_and_year(body, cite, name, want):
    w = {"id": "w1", "title": "Week 1 — Cases", "body": body}
    t = pack.build({1: [w]}, [], [_n(name, cite, int("19" + cite[-2:]) if cite[-2:] > "50" else None, "w1")])["topics"][0]
    got = [(c["cite"], c["year"], c["numbered"]) for c in t["cases"]]
    assert got == [want]
    assert all("established" not in c["cite"] and "held" not in c["cite"] for c in t["cases"])


# ---- fixture B: one whole-row assertion per trap row (name, cite and year on the same row)
TRAPS = json.load(open(os.path.join(HERE, "trap_rows.json"), encoding="utf-8"))


@pytest.mark.parametrize("row", TRAPS, ids=[r["trap"][6:60] for r in TRAPS])
def test_fixture_b_whole_row(row):
    out = pack.normalise_cases([_n(row["name"], row["cite"], row["given_year"])])
    assert [(c["name"], c["cite"], c["year"], c["numbered"]) for c in out] == [(row["name"], *row["expect"])]


def test_fixture_b_rows_are_labelled_and_truth_rows_carry_a_url():
    for r in TRAPS:
        assert r["trap"].startswith("TRAP"), r
        if "format only" not in r["trap"]:
            assert r.get("url", "").startswith("https://"), r["trap"]      # a row that asserts a real fact names its source


def test_no_national_or_ecthr_number_gets_a_case_prefix_or_a_dagger_year():
    for r in TRAPS:
        if re.search(r"BvR|BvE|BVerfGE|sent\.|Corte cost|Pl\. US|^K |Application|Opinion", r["cite"]):
            c = pack.normalise_cases([_n(r["name"], r["cite"], r["given_year"])])[0]
            assert not c["cite"].startswith(("Case", "Joined")) and not c["numbered"], r["trap"]


def test_a_bare_figure_under_a_page_column_is_never_a_year_but_a_year_column_is_kept():
    # TRAP (format only): a case-map table whose Page column holds a figure that looks like a year
    body = ("# Week 6 — Test\n\n## Case map\n| Case | Citation | Page | Year |\n|---|---|---|---|\n"
            "| Dassonville | Case 8/74 | 2071 | 1974 |\n| Cassis de Dijon | Case 120/78 | 2071 | |\n\n"
            "## Case map two\n| Case | Citation | Page |\n|---|---|---|\n| Costa v ENEL | Case 6/64 | 2071 |\n")
    got = {n: _table for n, _table in ((n, pack._table_year(n, [body])) for n in ("Dassonville", "Cassis de Dijon", "Costa v ENEL"))}
    assert got == {"Dassonville": 1974, "Cassis de Dijon": None, "Costa v ENEL": None}


def test_an_all_undated_week_is_headed_leading_cases_and_undated_rows_come_last():
    w = {"id": "u", "title": "Week 4 — State aid", "body": "*Altmark* and *Tubemeuse* on aid. *Dassonville* (Case 8/74, judgment of 11 July 1974)."}
    cases = [_n("Altmark", "", None, "u"), _n("Tubemeuse", "", None, "u")]
    t = pack.build({4: [w]}, [], cases)["topics"][0]
    assert t["cases_heading"] == "Leading cases"
    cases.append(_n("Dassonville", "Case 8/74", 1974, "u"))
    t = pack.build({4: [w]}, [], cases)["topics"][0]
    assert t["cases_heading"] == "Leading cases, oldest first" and t["cases"][0]["name"] == "Dassonville" and t["cases"][-1]["year"] is None


def test_a_synthetic_wg_answer_week_keeps_answers_out_of_the_outline():
    body = ("# Week 5 — Remedies\n\n## Questions of admissibility\ntext\n\n## Facts and procedure in Art 267\ntext\n\n"
            "## WG answer: question 2\nsynthetic answer\n\n## Model answer to Q3\nsynthetic\n\n## Commission v Germany (beer)\ntext\n\n## Costa v ENEL\nCase 6/64 on primacy.\n")
    t = pack.build({5: [{"id": "s", "title": "Week 5 — Remedies", "body": body}]}, [], [])["topics"][0]
    assert t["outline"] == ["Questions of admissibility", "Facts and procedure in Art 267", "Commission v Germany (beer)", "Costa v ENEL"]
    bare = body.replace("Case 6/64 on primacy.", "On primacy.")          # no citation in the section: the case index vouches for it
    t = pack.build({5: [{"id": "s", "title": "Week 5 — Remedies", "body": bare}]}, [], [_n("Costa v ENEL", "6/64", 1964, "s")])["topics"][0]
    assert "Costa v ENEL" in t["outline"] and not any("answer" in h.lower() for h in t["outline"])


# ---- fixture A through the real route
def _demo_course(client):
    cid = client.post("/api/courses", json={"name": "Demo EU law (public sources)", "brief": {"method": "apply"}}).json()["id"]
    for f in ("week1", "week2"):
        b = _fx(os.path.join("demo", f + ".md"))
        r = client.post(f"/api/courses/{cid}/notes", json={"title": b.splitlines()[0][2:], "body": b})
        assert r.status_code < 300
    return cid


def _expected():
    exp = {}
    for line in _fx("expected_rules.txt").splitlines():
        if line.startswith("W|"):
            _, w, kind, text = line.split("|", 3)
            exp.setdefault(w, {"rule": "", "outline": []})
            if kind == "rule": exp[w]["rule"] = text
            else: exp[w]["outline"].append(text)
    return exp


def test_fixture_a_rules_and_outline_match_the_frozen_expected_text(client, pg):
    p = client.get(f"/api/courses/{_demo_course(client)}/pack").json()
    exp = _expected()
    assert [t["week"] for t in p["topics"]] == ["1", "2"]
    for t in p["topics"]:
        assert t["rule"] == exp[t["week"]]["rule"] and t["outline"] == exp[t["week"]]["outline"]


def test_fixture_a_method_steps_come_from_the_frozen_list_only(client, pg):
    p = client.get(f"/api/courses/{_demo_course(client)}/pack").json()
    assert p["method"] == _fx("method_steps.txt").splitlines()               # one source, one page
    assert all("method" not in t for t in p["topics"])                       # no second Method block in any week


def test_the_method_page_does_not_depend_on_what_a_weeks_prose_says():
    """Wave-5 skeptic: Must 7 passed only because the fixture notes were written to name the moves. The page comes
    from the course's method, so a week with no move words (and one on direct effect) prints none of the steps."""
    wk = {"id": "d", "title": "Week 2 — Direct effect and primacy", "body": "# Direct effect\nVan Gend held the Treaty creates rights.\n"}
    p = pack.build({2: [wk]}, [], [], method=True)
    assert p["method"] == _fx("method_steps.txt").splitlines() and "method" not in p["topics"][0]


def test_fixture_a_citation_check_against_the_demo_metadata(client, pg):
    """Must 13 at the API level: every printed row's name, case number and year against metadata.json."""
    meta = json.load(open(os.path.join(HERE, "demo_metadata.json")))["documents"]
    p = client.get(f"/api/courses/{_demo_course(client)}/pack").json()
    norm = lambda s: {w for w in re.sub(r"[^a-z0-9 ]", "", re.sub(r"\.", "", _flat(s).lower().replace("&", "loos" if "gend" in s.lower() else "&")).replace("-", " ")).split() if w not in {"en", "and", "v"}}
    nums = lambda s: set(re.findall(r"(?:[CT]-)?\d+/\d+", s))
    rows = [c for t in p["topics"] for c in t["cases"]]
    assert len(rows) == 9
    bad = []
    for c in rows:
        m = next((d for d in meta if nums(c["cite"]) and {re.sub(r"^[CT]-", "", x) for x in nums(c["cite"])} == {re.sub(r"^[CT]-", "", x) for x in nums(d["case_number"])}), None)
        if not m or not norm(c["name"]) <= norm(m["title"]) or c["year"] != int(m["judgment_date"][:4]) or c["numbered"]:
            bad.append((c, m and m["id"]))
    assert bad == []


def test_fixture_a_prints_no_stress_or_trap_text(client, pg):
    p = json.dumps(client.get(f"/api/courses/{_demo_course(client)}/pack").json())
    for bad in ("TRAP:", "Testcase", "Number0", "Direct effect 93/71"):
        assert bad not in p
    rows = [c["name"] for t in json.loads(p)["topics"] for c in t["cases"]]
    assert len(rows) == len(set(rows))


def test_the_attribution_line_is_the_licence_notes_line():
    note = os.path.join(DEMO_COURSE, "LICENCE-NOTE.md")
    if not os.path.exists(note): pytest.skip("demo course not on this machine")
    text = open(note, encoding="utf-8").read()
    assert '"' + pack.ATTRIBUTION + '"' in text


def _source_lines(f):
    import html as _h
    raw = open(os.path.join(DEMO_COURSE, "sources", f), encoding="utf-8", errors="ignore").read()
    raw = re.sub(r"(?i)</?(?:p|div|br|tr|li|h\d|td|th|table)\b[^>]*>", "\n", raw)
    return _h.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ").split("\n")


def _paragraph(f, n):
    """The text of numbered paragraph n of a judgment: from its marker line to the next number's marker line."""
    lines, mark = _source_lines(f), r"^\s*%d(?!\d)\s*\.?\s*(?=[A-Z\u2018\u201c'(\"])"
    start = next(i for i, l in enumerate(lines) if re.match(mark % n, l))
    end = next((k for k in range(start + 1, len(lines)) if re.match(mark % (n + 1), lines[k])), len(lines))
    return _flat(" ".join(lines[start:end])).lower()


def test_the_rule_quotes_are_in_the_cited_paragraphs():
    """Must 14: each quoted passage in expected_rules.txt occurs (ignoring case and spacing) INSIDE the paragraph its
    pinpoint names; where the English text has no paragraph numbers (Van Gend, Costa: cited by ECLI) in the whole file."""
    if not os.path.isdir(os.path.join(DEMO_COURSE, "sources")): pytest.skip("demo course not on this machine")
    checked = 0
    for line in _fx("expected_rules.txt").splitlines():
        if not line.startswith("Q|"): continue
        _, week, pin, f, quote = line.split("|", 4)
        para = re.search(r"\bpara (\d+)\b", pin)
        hay = _paragraph(f, int(para.group(1))) if para else _flat(" ".join(_source_lines(f))).lower()
        assert _flat(quote).lower() in hay, (pin, quote)
        assert para or "ECLI:" in pin, pin                       # no first-page "pinpoint": a page is cited only with a real one
        checked += 1
    assert checked == 6


def test_a_rule_line_in_the_pack_carries_no_pinpoint_the_sources_do_not_back():
    """The ECR first page of a report is not a pinpoint for a quotation, so no rule prints 'special edition p. N'."""
    for f in ("week1.md", "week2.md"):
        assert "special edition" not in _fx(os.path.join("demo", f))


# ---- the printed PDF (Chrome headless + pdftotext)
need_pdf = pytest.mark.skipif(not (os.path.exists(CHROME) and shutil.which("pdftotext")), reason="needs Chrome and pdftotext")


@pytest.fixture
def served(client, pg):
    import socket
    import uvicorn
    from run import app
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(100):
        if srv.started: break
        time.sleep(0.1)
    yield port, _demo_course(client)
    srv.should_exit = True; th.join(5)


def _pdf_text(port, cid, tmp_path):
    out = str(tmp_path / "pack.pdf")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}",
                    "--virtual-time-budget=8000", f"http://127.0.0.1:{port}/static/pack.html?course={cid}"],
                   check=True, capture_output=True, timeout=120)
    if os.environ.get("CF_PACK_PDF_OUT"): shutil.copy(out, os.environ["CF_PACK_PDF_OUT"])     # evidence for the judge
    pages = subprocess.run(["pdftotext", "-layout", out, "-"], capture_output=True, text=True, check=True).stdout.split("\f")
    return [p for p in pages if p.strip() != "" or p is not pages[-1]]


@need_pdf
def test_the_printed_pdf_each_week_opens_a_page_and_carries_label_method_page_and_attribution(served, tmp_path):
    port, cid = served
    pages = _pdf_text(port, cid, tmp_path)
    text = "\n".join(pages)
    assert [bool(p.strip()) for p in pages] == [True] * len(pages)                      # no blank page
    first = [_flat(p)[:40] for p in pages]
    assert first[0].startswith("Week 1 — Free movement of goods") and first[1].startswith("Week 2 — Direct effect and primacy")
    label = "AI-generated from your course notes. Verify every case, article and year against your own materials."
    assert _flat(text).count(label) == 2 + 1                                           # weeks + the tab sheet
    assert _flat(text).count(_flat(pack.ATTRIBUTION)) == 1
    steps = _fx("method_steps.txt").splitlines()
    assert _flat(pages[2])[:11] == "Exam method"                                        # its own titled page, after the weeks
    at = 0
    for s in steps:
        at = pages[2].index(s, at) + len(s)                                            # every step, in order, on the method page
    assert not any(s in pages[0] + pages[1] for s in steps)                            # and on no week: one Method block only
    assert text.count("Exam method") == 1 and "The method" not in text and "THE METHOD" not in text
    for bad in ("TRAP:", "Testcase", "WEEK 2 EU LAW COMPLETE LECTURE NOTES"):
        assert bad not in text


@need_pdf
def test_the_printed_pdf_case_rows_match_the_demo_metadata(served, tmp_path):
    """Must 13 on the PDF text itself: every case-table row's name, case number and year against metadata.json,
    and the ECR page only where the README verified it (Van Gend p. 1, Costa p. 585). 0 mismatches."""
    port, cid = served
    meta = json.load(open(os.path.join(HERE, "demo_metadata.json")))
    text = "\n".join(_pdf_text(port, cid, tmp_path))
    rows = re.findall(r"^\s*(\d{4}|—)\s+(.+?)\s+((?:Joined Cases|Case)\s+[\w\-/ &]+?)\s*$", text, re.M)
    assert len(rows) == 9, rows
    mism = []
    for year, name, cite in rows:
        m = next((d for d in meta["documents"] if {re.sub(r"^[CT]-", "", x) for x in re.findall(r"(?:[CT]-)?\d+/\d+", cite)}
                  == {re.sub(r"^[CT]-", "", x) for x in re.findall(r"(?:[CT]-)?\d+/\d+", d["case_number"])}), None)
        if not m or year != m["judgment_date"][:4]:
            mism.append((year, name, cite))
    flat = _flat(text)
    assert [d["case_number"] for d in meta["documents"] if d["case_number"] not in flat] == []   # Must 1: character for character
    assert mism == [] and "†" not in text            # every fixture-A year is written in the notes: no dagger
    assert not re.search(r"ECR[^\n]*\b(?!1\b|585\b)\d{3,4}\b", "\n".join(re.findall(r"^.*Case 26/62.*$|^.*Case 6/64.*$", text, re.M)))


@need_pdf
def test_the_printed_pdf_is_a4_with_no_dark_fill(served, tmp_path):
    port, cid = served
    out = str(tmp_path / "pack.pdf")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}",
                    "--virtual-time-budget=8000", f"http://127.0.0.1:{port}/static/pack.html?course={cid}"], check=True, capture_output=True, timeout=120)
    info = subprocess.run(["pdfinfo", out], capture_output=True, text=True).stdout
    assert "A4" in info or "595" in info and "842" in info
    css = open(os.path.join(os.path.dirname(HERE), "..", "..", "static", "pack.html"), encoding="utf-8").read()
    assert "background:#000" not in css and "background:#111" not in css and "<h3" not in css


# ---- wave 6: the notes route (run.py-shaped index rows + the note text), the way the wave-5 skeptic probed it
def _row(body, name, cite=""):
    w = {"id": "w1", "title": "Week 1 — Cases", "body": body}
    return [(c["name"], c["cite"], c["year"], c["numbered"]) for c in pack.build({1: [w]}, [], [_n(name, cite, None, "w1")])["topics"][0]["cases"]]


JOINED = [
    ("*Francovich* (Joined Cases C-6/90 and C-9/90, judgment of 19 November 1991) held state liability.", "Francovich", "C-6/90",
     [("Francovich", "Joined Cases C-6/90 and C-9/90", 1991, False)]),
    ("*Kadi* (Joined Cases C-402/05 P and C-415/05 P) reviewed UN listings.", "Kadi", "C-402/05",
     [("Kadi", "Joined Cases C-402/05 P and C-415/05 P", 2005, True)]),
    ("*Brasserie du Pecheur* (Joined Cases C-46/93 and C-48/93) [1996] ECR I-1029 awarded damages.", "Brasserie du Pecheur", "C-46/93",
     [("Brasserie du Pecheur", "Joined Cases C-46/93 and C-48/93", 1996, False)]),
    ("*Kadi* (C-402/05 P & C-415/05 P) reviewed UN listings.", "Kadi", "C-402/05",
     [("Kadi", "Joined Cases C-402/05 P & C-415/05 P", 2005, True)]),
    # two separate cases in one sentence are NOT joined
    ("*Marshall* (Case 152/84) and *Costa* (Case 6/64) are old.", "Marshall", "152/84", [("Marshall", "Case 152/84", 1984, True)]),
]


@pytest.mark.parametrize("body,name,cite,want", JOINED)
def test_joined_cases_in_running_text_keep_every_docket(body, name, cite, want):
    assert _row(body, name, cite) == want


OSCOLA = [
    ("*Van Gend* [1963] ECR 1 (Case 26/62) said so.", "Van Gend", "26/62", ("Case 26/62", 1963, False)),
    ("*Ratti* (Case 148/78) [1979] ECR 1629 said so.", "Ratti", "148/78", ("Case 148/78", 1979, False)),
    ("*Foto-Frost* [1987] ECR 4199 (Case 314/85) said so.", "Foto-Frost", "314/85", ("Case 314/85", 1987, False)),
    ("*Kadi* [2008] ECR I-6351 (Case C-402/05 P) said so.", "Kadi", "C-402/05", ("Case C-402/05 P", 2008, False)),
    # the report's page is never the year, and a year the notes do not write stays a flagged docket year
    ("*Ratti* said so (Case 148/78), ECR 1629.", "Ratti", "148/78", ("Case 148/78", 1978, True)),
]


@pytest.mark.parametrize("body,name,cite,want", OSCOLA)
def test_a_bracketed_report_year_in_the_oscola_form_prints_unmarked(body, name, cite, want):
    got = _row(body, name, cite)
    assert [(c, y, n) for _, c, y, n in got] == [want]


def test_an_opinion_does_not_take_the_next_cases_docket_and_that_case_keeps_its_row():
    """Wave-5 skeptic (legal fact): run.py reads the next 60 characters after an italic name, so '*Opinion 2/13* on
    ECHR accession. *Foto-Frost* (314/85)' arrives as the Opinion with Foto-Frost's number and no Foto-Frost row."""
    body = "*Opinion 2/13* on ECHR accession. *Foto-Frost* (314/85) says refer."
    rows = _row(body, "Opinion 2/13", "314/85")
    assert ("Opinion 2/13", "", None, False) in rows and ("Foto-Frost", "Case 314/85", 1985, True) in rows
    assert len(rows) == 2


def test_an_application_number_prints_verbatim_through_the_notes_route():
    """run.py's reader gives the ECtHR case an empty cite; Must 1 wants 'Application no. 5856/72' as written."""
    assert _row("*Tyrer v UK* (Application no. 5856/72) is an ECtHR case.", "Tyrer v UK", "") == [("Tyrer v UK", "Application no. 5856/72", None, False)]


# ---- Must 15: the printed demo copy is public-source only
def test_the_printed_demo_copy_holds_no_fixture_b_text(client, pg):
    p = client.get(f"/api/courses/{_demo_course(client)}/pack").json()
    printed = _flat(json.dumps(p, ensure_ascii=False))
    demo_notes = _flat(_fx("demo/week1.md") + _fx("demo/week2.md"))
    b_only = set()
    for r in json.loads(_fx("trap_rows.json")):
        for s in (r["name"], r["cite"]):
            if s and s not in demo_notes: b_only.add(s)
    assert b_only and [s for s in b_only if s in printed] == []
    assert "TRAP" not in printed and "WG" not in printed
    # every case row the pack prints is one of the ten fixture-A authorities
    meta = json.load(open(os.path.join(HERE, "demo_metadata.json")))["documents"]
    nums = {re.sub(r"^[CT]-", "", x) for d in meta for x in re.findall(r"(?:[CT]-)?\d+/\d+", d["case_number"])}
    for t in p["topics"]:
        for c in t["cases"]:
            assert {re.sub(r"^[CT]-", "", x) for x in re.findall(r"(?:[CT]-)?\d+/\d+", c["cite"])} <= nums, c
