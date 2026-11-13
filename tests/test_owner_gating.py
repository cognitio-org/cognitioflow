"""Owner-gating / IDOR (PR #3). Course CONTENT is read-shared to every allowed user but EDITED only by its owner
(courses.user_id); practice and progress stay open to all and are kept private per-user by PRs #1/#2. AUTH=off signs
in as the FIRST ALLOWED_EMAILS address, so monkeypatching that env switches the acting user for the next request
(_uid() re-resolves every call — no cache). 'A' is matej (the default owner); 'B' is a second allow-listed user."""
import time
import uuid

import pytest

OWNER = "matej@mgms.eu"


@pytest.fixture(autouse=True)
def _pin_owner(monkeypatch):
    """Pin the owner to A. Without this, owner_email() falls back to the FIRST ALLOWED_EMAILS address, so _act_as
    would silently make B the owner and A's course a student's private course (404 instead of 403 with the patch)."""
    monkeypatch.setenv("OWNER_EMAIL", OWNER)


def _act_as(monkeypatch, email):
    """Make `email` the signed-in user for subsequent requests (keep matej allow-listed for A's own setup calls).
    B also acknowledges the privacy notice, which the multi-user app requires before any other /api call (428);
    on an app without the multi-user routes the acknowledgement route does not exist and is skipped."""
    monkeypatch.setenv("ALLOWED_EMAILS", f"{email},{OWNER}")
    if email != OWNER:
        from fastapi.testclient import TestClient
        import run
        r = TestClient(run.app).put("/api/me/privacy", json={"privacy_ack": True})
        assert r.status_code in (200, 404, 405), r.status_code


def _owned_course(client):
    """A course created THROUGH the API by A, so courses.user_id is a concrete owner (not a NULL-owner seed)."""
    return client.post("/api/courses", json={"name": "A's private course"}).json()["id"]


def test_a_second_user_is_refused_every_content_write(client, monkeypatch):
    cid = _owned_course(client)                                             # A owns it
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "q", "back": "a"}).json()["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "N", "body": "b"}).json()["id"]

    _act_as(monkeypatch, "classmate@example.com")                          # now acting as B
    import io
    assert client.put(f"/api/courses/{cid}", json={"name": "hijack"}).status_code == 403
    assert client.post(f"/api/courses/{cid}/cards", json={"front": "x", "back": "y"}).status_code == 403
    assert client.post(f"/api/courses/{cid}/notes", json={"title": "x", "body": "y"}).status_code == 403
    assert client.post(f"/api/courses/{cid}/files",
                       files={"file": ("w.txt", io.BytesIO(b"text"), "text/plain")}, data={"week": "1"}).status_code == 403
    assert client.put(f"/api/cards/{kid}", json={"front": "x", "back": "y"}).status_code == 403    # by-id IDOR
    assert client.delete(f"/api/cards/{kid}").status_code == 403                                   # by-id IDOR
    assert client.delete(f"/api/notes/{nid}").status_code == 403                                   # by-id IDOR
    assert client.delete(f"/api/courses/{cid}?force=1").status_code == 403


def test_bs_refused_delete_leaves_as_content_intact(client, pg, monkeypatch):
    cid = _owned_course(client)
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "keep", "back": "me"}).json()["id"]

    _act_as(monkeypatch, "classmate@example.com")
    assert client.delete(f"/api/cards/{kid}").status_code == 403
    assert client.delete(f"/api/courses/{cid}?force=1").status_code == 403

    assert pg.execute("SELECT 1 FROM courses WHERE id=%s", (cid,)).fetchone() is not None
    assert pg.execute("SELECT 1 FROM cards WHERE id=%s", (kid,)).fetchone() is not None


def test_a_second_user_can_still_read_and_practice_shared_content(client, monkeypatch):
    cid = _owned_course(client)
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "q", "back": "a"}).json()["id"]

    _act_as(monkeypatch, "classmate@example.com")
    assert client.get(f"/api/courses/{cid}/cards").status_code == 200           # reads shared content
    r = client.post(f"/api/cards/{kid}/review", json={"rating": 2})             # practices — private per-user
    assert r.status_code == 200


def test_two_users_each_hold_an_attempt_on_the_same_question(client, pg, monkeypatch):
    """The essay-key drop (033): with the single-column essay_attempts_question_id_key gone, a second user can hold
    their OWN attempt on a question a classmate already answered. Both rows must persist (per-user uniqueness only)."""
    cid = _owned_course(client)
    qid = uuid.uuid4().hex[:10]
    pg.execute("INSERT INTO essay_questions(id,course_id,week,question,created) VALUES(%s,%s,'1','Q?',%s)",
               (qid, cid, time.time()))
    pg.commit()

    assert client.post(f"/api/courses/{cid}/essay/answer",
                       json={"question_id": qid, "answer": "A's answer"}).status_code == 200
    _act_as(monkeypatch, "classmate@example.com")
    assert client.post(f"/api/courses/{cid}/essay/answer",
                       json={"question_id": qid, "answer": "B's answer"}).status_code == 200       # not owner-gated

    rows = pg.execute("SELECT user_id, answer FROM essay_attempts WHERE question_id=%s ORDER BY answer", (qid,)).fetchall()
    assert [r[1] for r in rows] == ["A's answer", "B's answer"]                 # two separate rows
    assert rows[0][0] != rows[1][0] and all(r[0] for r in rows)                 # distinct, non-null user_ids


def test_a_file_from_another_course_cannot_be_borrowed_in_the_body(client):
    """Body-param IDOR: even the owner of two courses cannot pull course X's file text into course Y's generator —
    the file lookup is scoped to the path course, so a foreign file_id is a clean 404 before any model is called."""
    import io
    cx = client.post("/api/courses", json={"name": "Course X"}).json()["id"]
    cy = client.post("/api/courses", json={"name": "Course Y"}).json()["id"]
    fid = client.post(f"/api/courses/{cx}/files",
                      files={"file": ("x.txt", io.BytesIO(b"Article 34 TFEU."), "text/plain")},
                      data={"week": "1"}).json()["id"]
    # file belongs to X; asking Y's generator to use it must not reach the model — 404, scoped out
    assert client.post(f"/api/courses/{cy}/cards/generate", json={"file_id": fid}).status_code == 404
