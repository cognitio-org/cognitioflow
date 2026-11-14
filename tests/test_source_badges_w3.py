"""Source-type badges, wave 3 of the RUG-pitch review (2026-11-14). One test per finding on PR #233.

Each test was written against the wave-2 branch first and failed there; the JS ones run the shipped helpers in node,
like tests/test_source_type_badges.py, so they test what the screen renders.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
PENDING = ROOT / "docs" / "pending-protected"
NODE = shutil.which("node")


def _fn(name: str) -> str:
    assert f"function {name}(" in JS, f"app.js has no function {name}()"
    i = JS.index(f"function {name}(")
    j = JS.index("{", JS.index(")", i))
    depth = 0
    for k in range(j, len(JS)):
        depth += {"{": 1, "}": -1}.get(JS[k], 0)
        if depth == 0:
            return JS[i:k + 1]
    raise AssertionError(f"unbalanced {name}")


def _const(name: str) -> str:
    m = re.search(rf"^const {name}=.*?;$", JS, re.M)
    assert m, f"app.js has no const {name}"
    return m.group(0)


def _node(consts, fns, script: str):
    if not NODE:
        pytest.skip("node not installed")
    pre = "\n".join([re.search(r"const esc=s=>[^\n]*?\}\[c\]\)\);", JS).group(0),
                     "let ctxById={}, ctxByName={};", "function C(){ return null }"]
                    + [_const(c) for c in consts] + [_fn(f) for f in fns])
    r = subprocess.run([NODE, "-e", pre + "\n" + script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


BADGE_CONSTS = ["ROLE_NAMES", "AUTH_DEFAULT", "AUTH_MAX", "MODEL_ANSWER_RX", "EXAM_NAME_RX", "ANSWER_WORD_RX",
                "NOT_ANSWER_RX", "ABOUT_ANSWERS_RX"]
BADGE_FNS = ["isAnswerFile", "authTagRole", "authRanks", "authRank", "srcTypeTitle", "srcTypeName", "authChip",
             "ctxIndex", "ctxLookup", "srcLink", "fmtChars", "mdLite", "isMarkdown", "srcPage", "cfTok", "readingSummary"]


# ---------------------------------------------------------------- the answer-file rule now drives the visible badge

NAMES = {
    # model answers: unticked, badged "Model answers"
    "Practice exam 2 - Model answers.pdf": True, "model_answer.docx": True, "Answer key wk2.pdf": True,
    "Mock exam 2024 answers.pdf": True, "Resit uitwerkingen.pdf": True, "Tentamen 2023 antwoordmodel.pdf": True,
    # wave-2 false positives (skeptic): guidance about answering, and WG answers to an exam
    "Exam 2 - how to answer problem questions.pdf": False, "Model answer guidance essay writing.pdf": False,
    "WG7 answers to the 2022 resit.pdf": False, "Working group 4 - answers to the mock exam.pdf": False,
    # wave-3 over-correction (skeptic + judge): an explicit "model answers" / "answer key" beats the WG/guide/tips veto
    "Answer key - practice exam (guide).pdf": True, "Model answers WG7 mock exam.pdf": True,
    "Resit 2022 model answers and examiner tips.pdf": True, "Exam 2023 model answer - how to score.pdf": True,
    "WG 5 answer key.pdf": True,
    # ...but not guidance ABOUT model answers
    "Model answers - writing tips.pdf": False, "Answer key guide for tutors.pdf": False,
    # never answer files
    "W3 WG assignment answers.txt": False, "Working group assignment 6 answers.pdf": False,
    "Questions and answers on free movement.pdf": False, "Practice exam 2.pdf": False, "Q&A session.pdf": False,
}
ROLE = {"Model answer guidance essay writing.pdf": "admin", "Exam 2 - how to answer problem questions.pdf": "lecture"}


def _role(n):
    return ROLE.get(n) or ("wg" if re.search(r"(?i)\bwg|working group", n) else "exam")


def test_answer_rule_has_no_false_positive_badge():
    out = _node(BADGE_CONSTS, BADGE_FNS, f"""
      const fs={json.dumps([{"name": n, "label": "", "role": _role(n)} for n in NAMES])};
      console.log(JSON.stringify(fs.map(f=>[isAnswerFile(f), authChip(f,authRanks())])));""")
    for (name, want), (got, chip) in zip(NAMES.items(), out):
        assert got is want, name
        assert ("Model answers</span>" in chip) is want, (name, chip)
    chips = dict(zip(NAMES, (c for _, c in out)))
    assert "WG notes</span>" in chips["WG7 answers to the 2022 resit.pdf"]
    assert "Course info</span>" in chips["Model answer guidance essay writing.pdf"]
    assert "Lecture</span>" in chips["Exam 2 - how to answer problem questions.pdf"]


def test_pending_server_rule_matches_the_screen():
    """docs/pending-protected/badges-readinglist.patch unticks on the server; it must agree with isAnswerFile() name
    for name, or the extension and the drop zone tick different files."""
    added = [ln[1:] for ln in (PENDING / "badges-readinglist.patch").read_text(encoding="utf-8").splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    src = "\n".join(added)
    start = src.index("_MODEL_ANSWER = ")
    end = src.index("\ndef role_by_name") if "\ndef role_by_name" in src else len(src)
    ns = {"re": re}
    exec(src[start:end], ns)   # the patch's own lines: the regexes and is_answer_file()
    for name, want in NAMES.items():
        assert ns["is_answer_file"](name) is want, name


# ---------------------------------------------------------------- "Answered from" agrees with Files

def test_answered_from_counts_files_and_names_notes_apart():
    """The server's used/trimmed lists carry note titles too, so '3 of 5 ticked files' counted a note as a file and
    named a source that is nowhere in Files."""
    out = _node(BADGE_CONSTS, BADGE_FNS, """
      const fs=[{id:'t',name:'TFEU.pdf',label:'TFEU Articles 34-36',selected:1,role:'reader'},
                {id:'d',name:'Dassonville.md',label:'',selected:1,role:'cases'},
                {id:'w',name:'W3 WG answers.md',label:'',selected:1,role:'wg'},
                {id:'o',name:'00 Course Overview.md',label:'',selected:1,role:'admin'}];
      ctxIndex(fs);
      console.log(JSON.stringify(readingSummary({used:['TFEU.pdf','Dassonville.md','Introduction note'],
                                                 trimmed:['W3 WG answers.md','00 Course Overview.md'],chars:3120})));""")
    assert "2 of 4 ticked files" in out and "3 of 5" not in out
    assert "Introduction note" in out and re.search(r"[Nn]ote[s]?\b[^<]*:.*Introduction note", out)
    assert 'data-open-src="t"' in out and 'data-open-src="d"' in out
    assert "Introduction note</button>" not in out


# ---------------------------------------------------------------- the source viewer

def test_markdown_source_renders_headings_and_lists_safely():
    out = _node(BADGE_CONSTS, BADGE_FNS, """
      const f={id:'d',name:'Dassonville <x>.md',label:'',role:'cases',kind:'md',chars:400,selected:1};
      const t={name:f.name,text:'# Dassonville\\n\\n## Facts\\nBelgian law <img src=x onerror=alert(1)>.\\n\\n## Why\\n- It defines **MEQR**\\n- Later limits'};
      console.log(JSON.stringify({md:srcPage(f,t,'/r'), txt:srcPage({...f,name:'a.txt',kind:'txt'},{...t,name:'a.txt'},'/r')}));""")
    md = out["md"]
    article = md[md.index('<article'):]
    assert "<h3>Facts</h3>" in article and "<li>It defines <b>MEQR</b></li>" in article and "<ul>" in article
    assert "# Dassonville" not in article and "## Facts" not in article and "- It defines" not in article
    assert "<img" not in md and "&lt;img" in md
    assert "## Facts" in out["txt"]   # plain text stays verbatim


def test_viewer_close_button_says_what_it_does_and_works_alone():
    """'Back to the tutor' went to whatever page opened the tab, and its handler lived in the opener: once that tab
    navigated away the button did nothing."""
    out = _node(BADGE_CONSTS, BADGE_FNS, """
      console.log(JSON.stringify(srcPage({id:'a',name:'a.md',kind:'md',chars:5,role:'cases'},{name:'a.md',text:'x'},'/r')));""")
    assert "Back to the tutor" not in out
    assert re.search(r'id="srcBack"[^>]*>[^<]*Close', out)
    script = re.search(r"<script>(.*?)</script>", out, re.S)
    assert script and "window.close()" in script.group(1) and "srcBack" in script.group(1)
    assert "home" not in _fn("openSource")   # nothing in the opener's scope is needed any more


def test_source_type_tooltip_makes_no_outranking_claim():
    """The Treaty file is badged '4 Reader' below '1 WG notes'; a tooltip saying a Treaty article outranks any study
    material contradicts the screen it sits on. The number is the course's study order of file kinds, nothing more."""
    out = _node(BADGE_CONSTS, BADGE_FNS, "console.log(JSON.stringify(srcTypeTitle('Reader',4)))")
    assert "outrank" not in out and "study order" in out and "not legal authority" in out


# ---------------------------------------------------------------- the Reading list at 1190 (pills, narrow layout)

def test_narrow_reading_box_gives_the_list_its_own_row_and_room():
    """At 1190 the Reading box was capped at 7.5rem and shared its row with "Answered from": the third pill was cut in
    half and the fourth hidden."""
    narrow = CSS[CSS.index("@media(max-width:1300px)"):]
    narrow = narrow[:narrow.index("\n}\n")]
    assert re.search(r"#ctxAnswer\{[^}]*flex-basis:100%", narrow)
    # app-after.css loads later and caps `.screen>.tutor aside.col` at 7.5rem: only a more specific selector (the id) wins
    assert re.search(r"#tutor>\.tutor>aside\.col\{[^}]*max-height:min\(", narrow)
