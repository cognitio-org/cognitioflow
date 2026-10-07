"""Read-only keys (approved 2026-10-02, for Jarvis): a cfr_ key may GET Today, the due counts and weak topics and
nothing else; only its hash is stored; only the owner's signed-in session makes, lists or revokes one."""
import pytest

import auth


@pytest.fixture
def key(client):
    r = client.post("/api/tokens")
    assert r.status_code == 200
    return r.json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_the_owner_makes_a_key_and_sees_it_once(client, key, pg):
    assert key["token"].startswith("cfr_") and len(key["token"]) > 40 and key["scope"] == "read"
    listed = client.get("/api/tokens").json()
    assert [k["id"] for k in listed] == [key["id"]] and "token" not in listed[0] and "hash" not in listed[0]
    stored = pg.execute("SELECT hash FROM api_tokens").fetchone()[0]
    assert stored == auth.token_hash(key["token"]) and key["token"] not in stored   # only the hash is kept


def test_it_reads_today_the_due_counts_and_weak_topics(client, key):
    cid = client.post("/api/courses", json={"name": "Key Law"}).json()["id"]
    client.post(f"/api/courses/{cid}/cards", json={"front": "q", "back": "a"})
    assert client.get("/api/today", headers=_h(key["token"])).status_code == 200
    due = client.get("/api/due", headers=_h(key["token"]))
    assert due.status_code == 200 and due.json()[cid] == 1
    assert client.get(f"/api/courses/{cid}/weak-topics", headers=_h(key["token"])).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("get", "/api/courses"), ("get", "/api/config"), ("get", "/api/courses/x/notes"), ("get", "/api/courses/x/messages"),
    ("get", "/api/tokens"), ("get", "/"), ("get", "/static/index.html"),
    ("post", "/api/today"), ("post", "/api/courses"), ("post", "/api/tokens"), ("delete", "/api/tokens/x"),
    ("post", "/api/courses/x/chat"), ("delete", "/api/courses/x/messages"),
])
def test_everything_else_is_refused(client, key, method, path):
    r = getattr(client, method)(path, headers=_h(key["token"]))
    assert r.status_code == 403 and "reads Today" in r.json()["detail"]


def test_it_can_never_write_even_to_the_routes_it_reads(client, key):
    for m in ("post", "put", "patch", "delete"):
        assert getattr(client, m)("/api/due", headers=_h(key["token"])).status_code == 403


def test_an_unknown_or_revoked_key_is_401(client, key):
    assert client.get("/api/today", headers=_h("cfr_" + "x" * 43)).status_code == 401
    assert client.get("/api/today", headers=_h("not-a-key")).status_code == 401
    assert client.delete(f"/api/tokens/{key['id']}").status_code == 200
    assert client.get("/api/today", headers=_h(key["token"])).status_code == 401
    assert client.get("/api/tokens").json()[0]["revoked"]


def test_a_key_sets_no_cookie(client, key):
    r = client.get("/api/today", headers=_h(key["token"]))
    assert "set-cookie" not in {k.lower() for k in r.headers}


def test_only_the_owner_can_make_keys(client, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "someone.else@example.com")
    assert client.post("/api/tokens").status_code == 403 and client.get("/api/tokens").status_code == 403


def test_a_key_for_an_address_taken_off_the_list_stops_working(client, key, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "other@example.com")
    assert client.get("/api/today", headers=_h(key["token"])).status_code == 401


def test_it_reads_mock_counts_and_nothing_of_the_text(client, key, pg):
    """Mock exams as counts only (Matej, 2026-10-07): the key sees hit/partly/missed counts, never a question,
    an answer, a model answer, a comment or a paper's name."""
    import json, time, uuid
    import mockexam
    cid = client.post("/api/courses", json={"name": "Mock Law"}).json()["id"]
    qid = uuid.uuid4().hex[:10]
    pg.execute("INSERT INTO essay_questions(id,course_id,week,question,model,source,created) VALUES(%s,%s,'',%s,%s,%s,%s)",
               (qid, cid, "SECRET QUESTION TEXT", "SECRET MODEL ANSWER", mockexam.source("June 2024", 1), time.time()))
    grade = {"kind": "mock", "points": [{"point": "SECRET POINT", "standing": "hit", "comment": "SECRET COMMENT"},
                                        {"point": "p2", "standing": "missed", "comment": "c"}],
             "missing": ["SECRET AUTHORITY"], "overall": "SECRET OVERALL"}
    pg.execute("INSERT INTO essay_attempts(id,question_id,course_id,answer,submitted,grade,updated) VALUES(%s,%s,%s,%s,%s,%s,%s)",
               (uuid.uuid4().hex[:10], qid, cid, "SECRET ANSWER", time.time(), json.dumps(grade), time.time()))
    pg.commit()
    r = client.get(f"/api/courses/{cid}/mock/summary", headers=_h(key["token"]))
    assert r.status_code == 200
    body = r.json()
    assert (body["papers"], body["papers_sat"], body["questions"], body["handed_in"]) == (1, 1, 1, 1)
    assert (body["hit"], body["partly"], body["missed"]) == (1, 0, 1) and body["last_handed_in"]
    assert "SECRET" not in r.text and "June 2024" not in r.text
    assert client.get(f"/api/courses/{cid}/mock/papers", headers=_h(key["token"])).status_code == 403
