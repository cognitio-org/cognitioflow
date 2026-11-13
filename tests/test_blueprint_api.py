"""Coverage map through the real endpoints (w3 regressions): extract checks the model's reply against the course's
own syllabus weeks and stated objectives, never sends past papers, and a Save keeps the real week count.
Needs docker Postgres (client/pg fixtures); run.ask_model is faked, so this asserts the wiring, not the model."""
import json
from types import SimpleNamespace as NS

import run

WEEKS = [{"week": str(n), "title": f"Week {n} title", "topics": [f"Topic {n}"], "readings": []} for n in (1, 2, 3, 4)]
OBJECTIVES = "Explain the free movement of goods\nApply Art 34 TFEU\nAnalyse direct effect"


def _reply(obj):
    return NS(content=[NS(type="text", text=json.dumps(obj))], stop_reason="end_turn")


def _course(client):
    cid = client.post("/api/courses", json={"name": "EU Coverage"}).json()["id"]
    assert client.post(f"/api/courses/{cid}/syllabus/apply", json={"weeks": WEEKS, "source": "syllabus.pdf"}).status_code == 200
    assert client.put(f"/api/courses/{cid}", json={"brief": {"learning_objectives": OBJECTIVES}}).status_code == 200
    return cid


def test_extract_drops_invented_weeks_and_objectives_and_save_keeps_the_real_count(client, monkeypatch):
    cid = _course(client)
    sent = []
    reply = {"topics": [
        {"topic": "Goods", "weeks": [1, 2], "objectives": [1, 2], "doctrines": ["Art 34 TFEU"]},
        {"topic": "Invented", "weeks": [30], "objectives": [9], "doctrines": ["Nothing"]},
        {"topic": "Direct effect", "weeks": [3], "objectives": [3], "doctrines": ["Van Gend"]},
    ], "note": "All stated learning objectives and syllabus weeks have been mapped to corresponding topics."}
    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (sent.append(k) or _reply(reply)))
    r = client.post(f"/api/courses/{cid}/blueprint/extract")
    assert r.status_code == 200, r.text
    b = r.json()
    t = {x["topic"]: x for x in b["topics"]}
    assert t["Invented"]["weeks"] == [] and t["Invented"]["objectives"] == [] and t["Invented"]["weight"] == 0
    assert b["weeks_total"] == 4 and b["weeks_unmapped"] == [4] and b["objectives_total"] == 3
    assert t["Goods"]["weight"] == 50 and t["Direct effect"]["weight"] == 25     # 2 of 4 and 1 of 4 weeks
    assert "<paper" not in sent[0]["messages"][0]["content"]

    assert client.post(f"/api/courses/{cid}/blueprint/apply", json=b).json()["applied"]
    saved = client.get(f"/api/courses/{cid}/blueprint").json()
    assert saved["weeks_total"] == 4 and saved["basis"] == "weeks"
    assert {x["topic"]: x["weight"] for x in saved["topics"]} == {"Goods": 50, "Direct effect": 25, "Invented": 0}
    rd = client.get(f"/api/courses/{cid}/readiness").json()
    assert {x["topic"]: x["weight"] for x in rd["topics"]}["Goods"] == 50


def test_extract_never_reads_past_papers(client, monkeypatch):
    cid = _course(client)
    # an exam file, seeded directly: the old extract fed its text to the model
    with run.db() as d:
        d.execute("INSERT INTO files(id,course_id,name,kind,role,text,created) VALUES(?,?,?,?,?,?,?)",
                  ("f-exam", cid, "Past exam 2024.pdf", "pdf", "exam", "Q1 Discuss Keck. SECRET-EXAM-TEXT", 0))
    sent = []
    monkeypatch.setattr(run, "ask_model", lambda *a, **k: (sent.append(k) or _reply({"topics": []})))
    assert client.post(f"/api/courses/{cid}/blueprint/extract").status_code == 200
    assert "SECRET-EXAM-TEXT" not in sent[0]["messages"][0]["content"]
