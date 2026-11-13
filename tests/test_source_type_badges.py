"""Source-type badges and the tutor's reading list (pitch fix, 2026-11-14).

The badge ranked the KIND of file but was titled "Authority rank", which a lawyer reads as legal authority. Reading-list
items were plain text, and the syllabus picker and the default tick both fell onto "Practice exam 2 - Model answers".
No JS runner here (CLAUDE.md), so these assert against the shipped source, like test_ui_defects.py.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_badge_is_called_source_type_not_authority_rank():
    assert "Authority rank" not in JS
    assert "<th>Type</th>" not in HTML and "Source type" in HTML
    assert 'id="srcTypeNote"' in HTML and "not a ranking of legal authority" in HTML


def test_reading_list_items_open_their_source():
    tutor = JS[JS.index("async function loadTutor"):]
    tutor = tutor[:tutor.index("const chars=")]
    assert 'data-open-src="${esc(f.id)}"' in tutor and "openSource(" in tutor
    assert "function openSource(" in JS and "/raw" in JS[JS.index("function openSource("):][:600]


def _answer_rx():
    m = re.search(r"const ANSWER_RX=/(.+?)/i;", JS)
    assert m, "ANSWER_RX missing"
    return re.compile(m.group(1).replace("\\\\", "\\"), re.I)


def test_answer_files_are_recognised_and_study_material_is_not():
    rx = _answer_rx()
    for n in ("Practice exam 2 - Model answers.pdf", "W3 WG assignment answers.txt", "model_answer.docx", "Answer key wk2.pdf"):
        assert rx.search(n), n
    for n in ("W1 WG complete notes (annotated).pdf", "Practice exam 2.pdf", "00 Course Overview.md", "Q&A session.pdf"):
        assert not rx.search(n), n


def test_upload_and_syllabus_default_skip_answer_files():
    up = JS[JS.index("async function upload("):][:900]
    assert "isAnswerFile(" in up and "toggle-to" in up and "on:false" in up
    syl = JS[JS.index("function sylFill("):][:1400]
    assert "isAnswerFile(" in syl and "f.role==='admin'" in syl
