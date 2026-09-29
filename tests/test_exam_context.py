"""The tutor reads a course in its order of authority, past exams first, not in upload order.

Found 2026-09-29: the EU case-law reader (903,479 characters, uploaded early) filled the whole 180,000-character
budget, and none of the lectures, WG notes or assignments reached the tutor.
"""
import io

import run


def _up(client, cid, name, text):
    return client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(text.encode()), "text/plain")}).json()["id"]


def test_past_exams_and_wg_notes_reach_the_tutor_before_a_huge_reader(client, monkeypatch):
    monkeypatch.setattr(run, "CONTEXT_CHAR_BUDGET", 5000)
    cid = client.post("/api/courses", json={"name": "Order Law"}).json()["id"]
    _up(client, cid, "Case law reader.txt", "READER " * 2000)             # uploaded first, 14,000 characters
    _up(client, cid, "W1 WG notes.txt", "WORKING GROUP question 1")
    _up(client, cid, "Practice exam 1.txt", "Question 1 (19 points): advise Marika")
    parts, _, _ = run.build_context(cid)
    text = "\n".join(parts)
    assert parts[0].startswith('<file name="Practice exam 1.txt"') and "WORKING GROUP question 1" in text
    assert text.index("advise Marika") < text.index("WORKING GROUP") < text.index("READER")


def test_practice_papers_and_model_answers_are_labelled_past_exams():
    for name in ("Practice exam 1.pdf", "Practice exam 2 - Model answers.pdf", "Mock exam 2025.pdf", "Past paper June.pdf"):
        assert run.role_by_name(name) == "exam", name
    assert run.role_by_name("Assignment for week 3 FINAL.pdf") == "assignment"
    assert run.role_by_name("W1 WG complete notes.pdf") == "wg"


def test_a_course_with_past_exams_drills_in_exam_shape(client, pg):
    cid = client.post("/api/courses", json={"name": "Exam Law"}).json()["id"]
    fid = _up(client, cid, "Practice exam 1.txt", "Question 1: advise Marika")
    assert client.get(f"/api/courses/{cid}/files").json()[0]["role"] == "exam"
    course = run.rows("SELECT * FROM courses WHERE id=?", cid)[0]
    system, _, _, _ = run._tutor_prompt(cid, course, "drill", False, "")
    assert run.EXAM_PREP_RULE in system[0]["text"] and "well rounded" in system[0]["text"]
    client.post(f"/api/files/{fid}/toggle")   # unticked: no past exams in play, no rule
    system, _, _, _ = run._tutor_prompt(cid, course, "drill", False, "")
    assert run.EXAM_PREP_RULE not in system[0]["text"]
