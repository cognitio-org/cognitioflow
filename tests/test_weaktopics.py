"""Weak topics (Phase 18b) over a fixed history: weak when recall over the last 20 is under 80% or an essay missed a
step in the last two drafts; under 5 reviews is "not yet known"; counts only, never a score out of 100."""
import json
import time

import weaktopics


def _rv(week, ratings, t0=0):
    return [(week, r, t0 + i) for i, r in enumerate(ratings)]


HISTORY = (
    _rv("1", [2] * 18 + [0] * 2)                  # 18/20: holding
    + _rv("2", [0] * 10 + [2] * 20)               # the old misses fall out of the last 20: 20/20, holding
    + _rv("3", [2, 0, 1, 0, 0, 2, 2, 0, 2, 2])    # 6/10 (Hard counts): weak
    + _rv("4", [2, 2, 2])                         # 3 reviews: not yet known
    + _rv("5", [2] * 12 + [0] * 4)                # 12/16 = 75%: weak
)
DRAFTS = [("1", [{"step": "Applicability", "met": True}], 1),
          ("6", [{"step": "Application", "met": False}, {"step": "Conclusion", "met": True}], 2),   # an essay miss alone makes it weak
          ("2", [{"step": "Rule", "met": False}], 1), ("2", [{"step": "Rule", "met": True}], 2), ("2", [{"step": "Rule", "met": True}], 3)]


def test_the_ranking_matches_a_fixed_history():
    r = weaktopics.rank(HISTORY, DRAFTS, {"3": "Week 3 — Transfer"})
    assert [t["week"] for t in r["weak"]] == ["3", "5", "6"]          # weakest recall first; the essay-only miss last
    assert r["weak"][0] == {"week": "3", "label": "Week 3 — Transfer", "reviews": 10, "recalled": 6, "missed": []}
    assert r["weak"][2]["missed"] == ["Application"]
    assert [t["week"] for t in r["holding"]] == ["1", "2"]            # week 2's Rule miss is older than its last two drafts
    assert [(t["week"], t["reviews"]) for t in r["unknown"]] == [("4", 3)]


def test_hard_counts_as_recalled():
    assert weaktopics.rank(_rv("1", [1] * 10), [])["holding"][0]["recalled"] == 10


def test_no_score_out_of_100_anywhere():
    blob = json.dumps(weaktopics.rank(HISTORY, DRAFTS))
    assert "%" not in blob and "score" not in blob and "percent" not in blob


def test_the_route_reads_the_review_log_and_the_essays(client, pg):
    cid = client.post("/api/courses", json={"name": "Weak Law"}).json()["id"]
    client.post(f"/api/courses/{cid}/notes", json={"title": "Week 3 — Transfer", "body": "Rule. " * 400})
    now = time.time()
    for i in range(6):
        kid = client.post(f"/api/courses/{cid}/cards", json={"front": f"f{i}", "back": "b", "week": "3"}).json()["id"]
        pg.execute("INSERT INTO reviews(id,card_id,rating,created) VALUES(%s,%s,%s,%s)", (f"r{i}", kid, 0 if i < 3 else 2, now + i))
    pg.execute("INSERT INTO essay_questions(id,course_id,week,question,created) VALUES('q1',%s,'4','Q?',%s)", (cid, now))
    pg.execute("INSERT INTO essay_attempts(id,question_id,course_id,criteria,submitted,created) VALUES('a1','q1',%s,%s,%s,%s)",
               (cid, json.dumps([{"step": "Remedies", "met": False}]), now, now))
    pg.commit()
    w = client.get(f"/api/courses/{cid}/weak-topics").json()
    assert [(t["week"], t["label"], t["recalled"], t["reviews"]) for t in w["weak"]][0] == ("3", "Week 3 — Transfer", 3, 6)
    assert any(t["week"] == "4" and t["missed"] == ["Remedies"] for t in w["weak"])
    assert client.get("/api/courses/nope/weak-topics").status_code == 404
