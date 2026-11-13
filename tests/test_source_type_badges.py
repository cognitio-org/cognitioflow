"""Source-type badges and the tutor's reading list (pitch fix #226 and its follow-up, 2026-11-14).

The badge ranked the KIND of file but was titled "Authority rank", which a lawyer reads as legal authority. Reading-list
items were plain text, and the syllabus picker and the default tick both fell onto "Practice exam 2 - Model answers".

The follow-up runs the shipped JS in node (the helpers are pure string builders), so the escaping and the name lookup
are tested by what they actually render, not by what the source text contains. CI's ubuntu runner has node; without
it those tests skip.
"""
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_storage_api import _pdf

STATIC = Path(__file__).resolve().parent.parent / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


# ---------------------------------------------------------------- wording

def test_badge_is_called_source_type_not_authority_rank():
    assert "Authority rank" not in JS
    assert "<th>Type</th>" not in HTML and "Source type" in HTML
    assert 'id="srcTypeNote"' in HTML and "not a ranking of legal authority" in HTML


def test_drop_zone_note_claims_nothing_the_server_does_not_do():
    """run.py still ticks every upload (the fix is a pending protected patch), so the screen must not promise that
    answer files 'arrive unticked': extension and ingest uploads, and files ticked before, would contradict it."""
    note = re.search(r'<p[^>]*id="srcTypeNote"[^>]*>(.*?)</p>', HTML, re.S).group(1)
    assert "unticked" not in note and "arrive" not in note


def test_show_reading_has_no_private_escaper():
    """#226 gave showReading its own esc() that skipped the double quote, and put file names in title="…"."""
    body = JS[JS.index("function readingSummary("):JS.index("function showCost(")]   # showReading renders readingSummary
    assert "function showReading(" in body and "readingSummary(r)" in body
    assert "const esc=" not in body and "srcLink(" in body


# ---------------------------------------------------------------- the shipped helpers, run in node

def _fn(name: str) -> str:
    """The source of one top-level `function name(…){…}` from app.js, by brace matching."""
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
    assert m, name
    return m.group(0)


HELPERS = "\n".join([
    re.search(r"const esc=s=>[^\n]*?\}\[c\]\)\);", JS).group(0),
    "let ctxById={}, ctxByName={};", "function C(){ return null }",
    _const("ROLE_NAMES"), _const("AUTH_DEFAULT"), _const("AUTH_MAX"),
    _const("MODEL_ANSWER_RX"), _const("EXAM_NAME_RX"), _const("ANSWER_WORD_RX"), _const("NOT_ANSWER_RX"),
] + [_fn(n) for n in ("isAnswerFile", "authTagRole", "authRanks", "authRank", "srcTypeTitle", "srcTypeName", "authChip",
                      "ctxIndex", "ctxLookup", "srcLink", "fmtChars", "ctxItem", "mdLite", "isMarkdown", "srcPage")])


def _node(script: str):
    if not NODE:
        pytest.skip("node not installed")
    r = subprocess.run([NODE, "-e", HELPERS + "\n" + script], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


HOSTILE = 'x" autofocus onfocus="alert(1)<img src=x onerror=alert(2)>.pdf'
ATTR = re.compile(r'\s([a-zA-Z-]+)="[^"]*"')


def _tags(html: str):
    """Every opening tag as (name, [attribute names]); an injected attribute shows up as an extra name."""
    return [(m.group(1), ATTR.findall(m.group(2))) for m in re.finditer(r"<([a-z0-9]+)((?:\s[^<>]*)?)>", html)]


def test_hostile_file_name_cannot_add_an_attribute_or_a_tag():
    out = _node(f"""
      const f={{id:'f1',name:{json.dumps(HOSTILE)},label:'',role:'wg',kind:'pdf',chars:2000,selected:1,week:'1'}};
      ctxIndex([f]);
      console.log(JSON.stringify({{link:srcLink(f.name,ctxLookup(f.name)), plain:srcLink(f.name,null), item:ctxItem(f,authRanks()),
        page:srcPage(f,{{name:f.name,text:'body '+f.name}},'/api/files/f1/raw')}}));""")
    assert _tags(out["link"]) == [("button", ["type", "class", "data-open-src", "title"])]
    assert _tags(out["plain"]) == []
    assert [t for t in _tags(out["item"]) if t[0] == "button"] == [("button", ["type", "class", "data-open-src", "title"])]
    assert all(t[0] in ("li", "span", "i", "button") for t in _tags(out["item"]))
    page_tags = {t[0] for t in _tags(out["page"])}
    assert "img" not in page_tags and not any("onfocus" in a or "autofocus" in a for _, a in _tags(out["page"]))
    for html in out.values():
        assert "onerror" not in "".join(" ".join(a) for _, a in _tags(html))


def test_answered_from_name_opens_the_right_file():
    out = _node("""
      const ticked={id:'a',name:'Dassonville.md',label:'Dassonville (Case 8/74)',selected:1};
      const copy={id:'b',name:'Dassonville.md',label:'Dassonville, week 2 copy',selected:0};
      const twinA={id:'c',name:'Notes.md',label:'',selected:1}, twinB={id:'d',name:'Notes.md',label:'',selected:1};
      const clash={id:'e',name:'Keck.pdf',label:'Notes.md',selected:0};
      ctxIndex([ticked,copy,twinA,twinB,clash]);
      const r={dup:ctxLookup('Dassonville.md'), twins:ctxLookup('Notes.md'), label:ctxLookup('Dassonville (Case 8/74)'),
               note:ctxLookup('My week 1 summary')};
      ctxIndex([{id:'z',name:'Other course.pdf',label:'',selected:1}]);
      r.after=ctxLookup('Dassonville.md');
      console.log(JSON.stringify({dup:r.dup&&r.dup.id, twins:r.twins, label:r.label&&r.label.id, note:r.note, after:r.after,
                                  shown:srcLink('Dassonville.md',r.dup)}));""")
    assert out["dup"] == "a"            # the ticked one wins over its unticked copy
    assert out["twins"] is None         # two ticked files with one name: plain text, never a guess
    assert out["label"] == "a"
    assert out["note"] is None          # note titles are in "used" too; they never match a file
    assert out["after"] is None         # switching course empties the index
    assert "Dassonville (Case 8/74)</button>" in out["shown"] and 'data-open-src="a"' in out["shown"]


def test_model_answers_get_their_own_badge_and_wg_answers_stay_wg():
    names = {
        "Practice exam 2 - Model answers.pdf": True, "model_answer.docx": True, "Answer key wk2.pdf": True,
        "Mock exam 2024 answers.pdf": True, "Resit uitwerkingen.pdf": True, "Tentamen 2023 antwoordmodel.pdf": True,
        "W3 WG assignment answers.txt": False, "Working group assignment 6 answers.pdf": False,
        "Questions and answers on free movement.pdf": False, "W1 WG complete notes (annotated).pdf": False,
        "Practice exam 2.pdf": False, "00 Course Overview.md": False, "Q&A session.pdf": False,
    }
    out = _node(f"""
      const names={json.dumps(list(names))};
      console.log(JSON.stringify(names.map(n=>{{ const f={{name:n,label:'',role:/exam|resit|tentamen/i.test(n)?'exam':'wg'}};
        return [isAnswerFile(f), authChip(f,authRanks())]; }})));""")
    for (name, want), (got, chip) in zip(names.items(), out):
        assert got is want, name
        assert ("Model answers</span>" in chip) is want, (name, chip)
        if not want and "WG" in name:
            assert "WG notes</span>" in chip


def test_small_files_show_a_real_size():
    out = _node("console.log(JSON.stringify([fmtChars(0),fmtChars(380),fmtChars(1251),fmtChars(12400),fmtChars(181000)]))")
    assert out == ["0 chars", "380 chars", "1.3k", "12k", "181k"]


def test_upload_unticks_model_answers_only_when_the_server_says_so():
    up = JS[JS.index("async function upload("):][:1200]
    assert "isAnswerFile(" in up and "toggle-to" in up and "on:false" in up
    assert "t.selected===0" in up and "could not untick" in up
    syl = JS[JS.index("function sylFill("):][:1400]
    assert "isAnswerFile(" in syl and "f.role==='admin'" in syl


# ---------------------------------------------------------------- the endpoints the reading list opens

def _upload(client, cid, name, data, week="1"):
    r = client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(data), "application/octet-stream")},
                    data={"week": week})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_reading_list_sources_open_pdf_and_markdown(client):
    cid = client.get("/api/courses").json()[0]["id"]
    pdf = _upload(client, cid, "TFEU Articles 34-36.pdf", _pdf("Article 34 TFEU quantitative restrictions"))
    md = _upload(client, cid, "Dassonville case note.md", "# Dassonville\n\nAll trading rules ... capable of hindering".encode())
    listed = {f["id"]: f for f in client.get(f"/api/courses/{cid}/files").json()}
    assert {"id", "name", "label", "role", "kind", "chars", "selected", "week"} <= set(listed[pdf])   # what ctxIndex/srcPage read
    for fid, needle, ctype in ((pdf, "Article 34", "application/pdf"), (md, "capable of hindering", None)):
        t = client.get(f"/api/files/{fid}/text").json()
        assert needle in t["text"] and t["name"] == listed[fid]["name"]
        raw = client.get(f"/api/files/{fid}/raw")
        assert raw.status_code == 200 and raw.content
        if ctype:
            assert raw.headers["content-type"] == ctype


def test_untick_answer_reports_the_state_the_toast_relies_on(client):
    cid = client.get("/api/courses").json()[0]["id"]
    fid = _upload(client, cid, "Practice exam 2 - Model answers.md", b"Model answer: Keck applies.")
    r = client.post(f"/api/files/{fid}/toggle-to", json={"on": False})
    assert r.status_code == 200 and r.json()["selected"] == 0
    assert [f["selected"] for f in client.get(f"/api/courses/{cid}/files").json() if f["id"] == fid] == [0]
