"""Today and the study view (2026-09-29): the greeting, each course's countdown and tasks, notes by week,
and the tutor reading his notes but never the saved chat replies."""
import unittest.mock as mock
from datetime import date, timedelta

import run


def _course_with_notes(client, pg, exam_in_days=20):
    cid = client.post("/api/courses", json={"name": "Countdown Law"}).json()["id"]
    exam = (run._local_today() + timedelta(days=exam_in_days)).isoformat()
    pg.execute("UPDATE courses SET exam_date=%s WHERE id=%s", (exam, cid)); pg.commit()
    for title, body in [("Week 1 — Ownership", "# Ownership\n" + "Rule. " * 400),
                        ("Week 2 — Transfer", "# Transfer\n" + "Rule. " * 400),
                        ("The method", "# Method\n" + "Step. " * 400),
                        ("I need to stop you here.", "I cannot save files.")]:
        client.post(f"/api/courses/{cid}/notes", json={"title": title, "body": body})
    return cid, exam


def test_today_greets_him_and_plans_every_course(client, pg):
    cid, exam = _course_with_notes(client, pg)
    t = client.get("/api/today").json()
    assert t["name"] and t["date"] == run._local_today().isoformat() and t["minutes"] == 180
    c = next(c for c in t["courses"] if c["id"] == cid)
    assert c["exam_date"] == exam and c["days_left"] == 20 and c["weeks"] == [1, 2] and c["week"] in (1, 2)
    if c["minutes"]:
        assert sum(x["minutes"] for x in c["tasks"]) == c["minutes"] and c["notes"][0]["title"].startswith(f"Week {c['week']}")


def test_the_study_view_sorts_notes_by_week_and_keeps_scraps_out_of_sight(client, pg):
    cid, _ = _course_with_notes(client, pg)
    s = client.get(f"/api/courses/{cid}/study").json()
    assert [w["week"] for w in s["weeks"]] == [1, 2] and s["weeks"][0]["notes"][0]["title"] == "Week 1 — Ownership"
    assert [n["title"] for n in s["reference"]] == ["The method"] and s["scraps"] == 1
    assert client.get("/api/courses/nope/study").status_code == 404


def test_the_tutor_reads_his_notes_but_not_the_saved_chat_replies(client, pg):
    cid, _ = _course_with_notes(client, pg)

    class FakeStream:
        text_stream = iter(["ok"])
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = mock.MagicMock()
    fake.messages.stream.return_value = FakeStream()
    with mock.patch.object(run, "client", return_value=fake):
        client.post(f"/api/courses/{cid}/chat", json={"message": "drill me", "mode": "drill"})
    system = fake.messages.stream.call_args.kwargs["system"]
    notes = next(b for b in system if b["text"].startswith("HIS NOTES"))
    assert "cache_control" in notes and "Week 1 — Ownership" in notes["text"] and "The method" in notes["text"]
    assert notes["text"].index("Week 1") < notes["text"].index("Week 2") < notes["text"].index("The method")
    assert "I cannot save files" not in notes["text"]


def test_the_day_is_his_timezone_not_the_servers():
    assert abs((run._local_today() - date.today()).days) <= 1
