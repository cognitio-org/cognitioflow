"""Mock exams through the API: his past papers banked verbatim, sat, handed in, marked against the model answer."""
import io
import json
import unittest.mock as mock

import run


def _reply(obj):
    r = mock.MagicMock(); r.content = [mock.MagicMock(type="text", text=json.dumps(obj))]; r.stop_reason = "end_turn"; r.model = "claude-test"
    return r


def _course_with_paper(client):
    cid = client.post("/api/courses", json={"name": "Mock Law"}).json()["id"]
    for name, text in [("Practice exam 1.txt", "Question 1 (19 points; estimated required time: 25 minutes)\nAdvise Marika."),
                       ("Practice exam 1 Model answers.txt", "Q1: Marika is a worker under Art 45 TFEU (Lawrie-Blum).")]:
        client.post(f"/api/courses/{cid}/files", files={"file": (name, io.BytesIO(text.encode()), "text/plain")})
    return cid


def test_a_paper_is_banked_word_for_word_once_and_sat_without_its_model_answer(client):
    cid = _course_with_paper(client)
    fake = mock.MagicMock()
    fake.messages.create.return_value = _reply([{"number": 1, "question": "Question 1 (19 points; estimated required time: 25 minutes)\nAdvise Marika.",
                                                 "model": "Marika is a worker under Art 45 TFEU (Lawrie-Blum)."}])
    with mock.patch.object(run, "client", return_value=fake):
        assert client.post(f"/api/courses/{cid}/mock/import").json()["imported"] == [{"paper": "Practice exam 1", "questions": 1}]
        assert client.post(f"/api/courses/{cid}/mock/import").json()["imported"] == []          # already banked: left alone
    sent = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Advise Marika." in sent and "Lawrie-Blum" in sent
    p = client.get(f"/api/courses/{cid}/mock/papers").json()["papers"][0]
    assert p["paper"] == "Practice exam 1" and p["minutes"] == 25
    q = p["questions"][0]
    assert q["points"] == 19 and "model" not in q and "Lawrie-Blum" not in json.dumps(p)
    assert client.get(f"/api/courses/{cid}/essay/{q['id']}/model").status_code == 409     # locked until handed in


def test_handing_in_unlocks_the_model_answer_and_marks_point_by_point(client):
    cid = _course_with_paper(client)
    fake = mock.MagicMock()
    fake.messages.create.return_value = _reply([{"number": 1, "question": "Question 1 (19 points)\nAdvise Marika.", "model": "Art 45 TFEU; Lawrie-Blum."}])
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/mock/import")
    qid = client.get(f"/api/courses/{cid}/mock/papers").json()["papers"][0]["questions"][0]["id"]
    fake.messages.create.return_value = _reply({"points": [{"point": "Worker under Art 45", "standing": "hit", "comment": "Good."}],
                                                "missing": ["Lawrie-Blum"], "overall": "Name the case.", "score": 15})
    with mock.patch.object(run, "client", return_value=fake):
        g = client.post(f"/api/courses/{cid}/mock/grade", json={"question_id": qid, "answer": "She works 34 hours, so Art 45 applies."}).json()
    assert g["kind"] == "mock" and g["points"][0]["standing"] == "hit" and "score" not in g
    marker = fake.messages.create.call_args.kwargs
    assert "OFFICIAL MODEL ANSWER" in marker["messages"][0]["content"] and "Never give a score" in marker["system"]
    assert client.get(f"/api/courses/{cid}/essay/{qid}/model").json()["model"] == "Art 45 TFEU; Lawrie-Blum."
    q = client.get(f"/api/courses/{cid}/mock/papers").json()["papers"][0]["questions"][0]
    assert q["submitted"] and q["grade"]["overall"] == "Name the case."
    assert client.post(f"/api/courses/{cid}/mock/reset", json={"paper": "Practice exam 1"}).json() == {"cleared": 1}
    assert not client.get(f"/api/courses/{cid}/mock/papers").json()["papers"][0]["questions"][0]["submitted"]


def test_nothing_written_is_handed_in_without_calling_the_marker(client):
    cid = _course_with_paper(client)
    fake = mock.MagicMock()
    fake.messages.create.return_value = _reply([{"number": 1, "question": "Question 1 (19 points)\nAdvise Marika.", "model": "x"}])
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/mock/import")
        qid = client.get(f"/api/courses/{cid}/mock/papers").json()["papers"][0]["questions"][0]["id"]
        calls = fake.messages.create.call_count
        g = client.post(f"/api/courses/{cid}/mock/grade", json={"question_id": qid, "answer": "  "}).json()
    assert g["overall"].startswith("Nothing was written") and fake.messages.create.call_count == calls


def test_only_the_words_within_the_limit_reach_the_marker(client):
    """The page says 'over the limit: only the first 300 are marked', so the marker must not read past them."""
    cid = _course_with_paper(client)
    fake = mock.MagicMock()
    fake.messages.create.return_value = _reply([{"number": 1, "question": "Question 1 (19 points; 25 minutes; max 50 words)\nAdvise Marika.", "model": "x"}])
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/mock/import")
        qid = client.get(f"/api/courses/{cid}/mock/papers").json()["papers"][0]["questions"][0]["id"]
        fake.messages.create.return_value = _reply({"points": [], "missing": [], "overall": "ok"})
        client.post(f"/api/courses/{cid}/mock/grade", json={"question_id": qid, "answer": "w " * 48 + "forty-nine\nfifty OVERFLOW"})
    sent = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "forty-nine\nfifty" in sent and "OVERFLOW" not in sent
