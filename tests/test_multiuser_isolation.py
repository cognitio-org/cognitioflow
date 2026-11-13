"""Two-user isolation + multi-user readiness (multiuser.py, migration 035).

A = matej@mgms.eu (the owner). B = a classmate. AUTH=off signs in as the FIRST ALLOWED_EMAILS address, so
_act_as() switches the acting user; OWNER_EMAIL is pinned so the owner stays A whichever address is first.

The shipped model (#178): course CONTENT (cards, notes, files) is shared and only its owner edits it; PROGRESS
(card schedule, reviews, chat, sessions, essays, AI use) is private per user. These tests prove the private half
never crosses between A and B, and that B still sees the shared half.

Tests marked `needs_patch` exercise docs/multi-user/protected-changes.patch (run.py/auth.py); they skip until it
is applied, and pass with it applied.
"""
import time
import uuid

import pytest

import llm
import multiuser
import run

A, B = "matej@mgms.eu", "classmate@example.com"
PATCHED = hasattr(run, "_see_course")
needs_patch = pytest.mark.skipif(not PATCHED, reason="needs docs/multi-user/protected-changes.patch (run.py/auth.py)")


@pytest.fixture
def mu(client, monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", A)
    monkeypatch.setenv("ALLOWED_EMAILS", A)
    multiuser.install(run.app, run.db, run._CALL)
    multiuser._INVITED.update(at=0.0, emails=frozenset())
    yield client
    if multiuser.cap_guard in llm.GUARDS:
        llm.GUARDS.remove(multiuser.cap_guard)


def _act_as(monkeypatch, email):
    monkeypatch.setenv("ALLOWED_EMAILS", f"{email},{A}" if email != A else A)


def _uid_of(pg, email):
    r = pg.execute("SELECT id FROM users WHERE email=%s", (email,)).fetchone()
    return r[0] if r else None


def _setup_a(client, pg):
    """A owns a course with a card and a note, reviews the card, logs a session, chats once, answers an essay."""
    cid = client.post("/api/courses", json={"name": "A's course"}).json()["id"]
    kid = client.post(f"/api/courses/{cid}/cards", json={"front": "Q-A", "back": "ans"}).json()["id"]
    client.post(f"/api/courses/{cid}/notes", json={"title": "A note", "body": "shared body"})
    assert client.post(f"/api/cards/{kid}/review", json={"rating": 3}).status_code == 200
    assert client.post(f"/api/courses/{cid}/sessions/log", json={"minutes": 25, "topic": "A studied"}).status_code == 200
    ua = _uid_of(pg, A)
    pg.execute("INSERT INTO messages(id,course_id,role,content,created,user_id) VALUES(%s,%s,'user','A private question',%s,%s)",
               (uuid.uuid4().hex[:10], cid, time.time(), ua))
    qid = uuid.uuid4().hex[:10]
    pg.execute("INSERT INTO essay_questions(id,course_id,week,question,created) VALUES(%s,%s,'1','Q?',%s)", (qid, cid, time.time()))
    pg.commit()
    assert client.post(f"/api/courses/{cid}/essay/answer", json={"question_id": qid, "answer": "A's essay"}).status_code == 200
    return cid, kid, qid


# ---------------------------------------------------------------- isolation on the live routes (no patch needed)
def test_b_never_sees_as_progress_but_sees_shared_content(mu, pg, monkeypatch):
    client = mu
    cid, kid, _ = _setup_a(client, pg)
    a_cards = {c["id"]: c for c in client.get(f"/api/courses/{cid}/cards").json()}
    assert a_cards[kid]["reps"] == 1                                   # A's schedule moved

    _act_as(monkeypatch, B)
    cards = client.get(f"/api/courses/{cid}/cards").json()            # shared content: visible
    assert [c["front"] for c in cards] == ["Q-A"]
    assert cards[0]["reps"] == 0 and cards[0]["last_review"] is None   # ...but A's schedule is not
    assert [n["title"] for n in client.get(f"/api/courses/{cid}/notes").json()] == ["A note"]
    assert client.get(f"/api/courses/{cid}/messages").json() == []    # A's chat: invisible
    s = client.get(f"/api/courses/{cid}/stats").json()
    assert (s["reviews"], s["study_minutes"], s["questions_asked"], s["streak"]) == (0, 0, 0, 0)
    assert all(x.get("topic") != "A studied" for x in client.get("/api/sessions").json())


def test_bs_own_progress_stays_out_of_as_view(mu, pg, monkeypatch):
    client = mu
    cid, kid, _ = _setup_a(client, pg)
    _act_as(monkeypatch, B)
    assert client.post(f"/api/cards/{kid}/review", json={"rating": 0}).status_code == 200
    client.post(f"/api/courses/{cid}/sessions/log", json={"minutes": 5, "topic": "B studied"})
    _act_as(monkeypatch, A)
    card = next(c for c in client.get(f"/api/courses/{cid}/cards").json() if c["id"] == kid)
    assert card["reps"] == 1                                           # B's "again" did not reset A
    assert client.get(f"/api/courses/{cid}/stats").json()["reviews"] == 1
    assert all(x.get("topic") != "B studied" for x in client.get("/api/sessions").json())


def test_b_cannot_edit_as_content(mu, pg, monkeypatch):
    client = mu
    cid, kid, _ = _setup_a(client, pg)
    _act_as(monkeypatch, B)
    assert client.put(f"/api/cards/{kid}", json={"front": "x", "back": "y"}).status_code == 403
    assert client.post(f"/api/courses/{cid}/cards", json={"front": "x", "back": "y"}).status_code == 403
    assert client.put(f"/api/courses/{cid}", json={"name": "hijack"}).status_code == 403


# ---------------------------------------------------------------- export / delete / consent
def test_export_holds_only_my_rows(mu, pg, monkeypatch):
    client = mu
    cid, kid, qid = _setup_a(client, pg)
    _act_as(monkeypatch, B)
    client.post(f"/api/cards/{kid}/review", json={"rating": 2})
    r = client.get("/api/me/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    body = r.json()
    ub = _uid_of(pg, B)
    assert body["user"]["email"] == B
    for table, rs in body["tables"].items():
        assert all(x["user_id"] == ub for x in rs), table               # nothing of A's leaks into B's export
    assert len(body["tables"]["reviews"]) == 1 and body["tables"]["messages"] == []
    assert body["tables"]["essay_attempts"] == [] and body["owned_course_content"] == {}

    _act_as(monkeypatch, A)
    mine = client.get("/api/me/export").json()
    assert {e["answer"] for e in mine["tables"]["essay_attempts"]} == {"A's essay"}
    assert cid in mine["owned_course_content"] and mine["owned_course_content"][cid]["cards"][0]["front"] == "Q-A"
    assert all("hash" not in t for t in mine["tables"].get("api_tokens", []))


def test_delete_erases_b_and_leaves_a_intact(mu, pg, monkeypatch):
    client = mu
    cid, kid, _ = _setup_a(client, pg)
    _act_as(monkeypatch, B)
    client.post(f"/api/cards/{kid}/review", json={"rating": 2})
    client.post(f"/api/courses/{cid}/sessions/log", json={"minutes": 5})
    ub = _uid_of(pg, B)
    assert client.post("/api/me/delete", json={"confirm": "wrong@example.com"}).status_code == 422
    r = client.post("/api/me/delete", json={"confirm": B})
    assert r.status_code == 200, r.text
    assert pg.execute("SELECT 1 FROM users WHERE id=%s", (ub,)).fetchone() is None
    for t in ("reviews", "sessions", "card_state", "messages", "essay_attempts"):
        assert pg.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=%s", (ub,)).fetchone()[0] == 0, t
    ua = _uid_of(pg, A)
    assert pg.execute("SELECT COUNT(*) FROM reviews WHERE user_id=%s", (ua,)).fetchone()[0] == 1
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE id=%s", (kid,)).fetchone()[0] == 1


def test_owner_and_course_owners_cannot_self_delete(mu, pg, monkeypatch):
    client = mu
    _setup_a(client, pg)
    assert client.post("/api/me/delete", json={"confirm": A}).status_code == 403          # the owner
    _act_as(monkeypatch, B)
    client.post("/api/courses", json={"name": "B's own course"})
    assert client.post("/api/me/delete", json={"confirm": B}).status_code == 409          # owns content: owner decides


def test_capture_consent_defaults(mu, pg, monkeypatch):
    client = mu
    _setup_a(client, pg)
    ua = _uid_of(pg, A)
    assert multiuser.capture_allowed(run.db, ua, A) is True            # owner: Phase 19 default stays on
    _act_as(monkeypatch, B)
    assert client.get("/api/me").json()["privacy"]["capture_consent"] is None
    ub = _uid_of(pg, B)
    assert multiuser.capture_allowed(run.db, ub, B) is False           # a student: off until they say yes
    assert client.put("/api/me/privacy", json={"capture_consent": True, "privacy_ack": True}).json()["capture_consent"] is True
    assert multiuser.capture_allowed(run.db, ub, B) is True
    client.put("/api/me/privacy", json={"capture_consent": False})
    assert multiuser.capture_allowed(run.db, ub, B) is False


# ---------------------------------------------------------------- invites + admin (owner only)
def test_invites_are_owner_only_and_send_nothing(mu, pg, monkeypatch):
    client = mu
    _setup_a(client, pg)
    r = client.post("/api/admin/invites", json={"email": "Student@Example.com", "note": "RUG"})
    assert r.status_code == 200 and r.json()["email"] == "student@example.com"
    assert client.post("/api/admin/invites", json={"email": "not-an-email"}).status_code == 422
    assert [i["email"] for i in client.get("/api/admin/invites").json()] == ["student@example.com"]
    assert "student@example.com" in multiuser.invited_emails(run.db, fresh=True)
    assert client.get("/api/admin/users").status_code == 200

    _act_as(monkeypatch, B)
    assert client.get("/api/admin/invites").status_code == 403
    assert client.post("/api/admin/invites", json={"email": "x@example.com"}).status_code == 403
    assert client.get("/api/admin/users").status_code == 403

    _act_as(monkeypatch, A)
    assert client.delete("/api/admin/invites/student@example.com").status_code == 200
    assert "student@example.com" not in multiuser.invited_emails(run.db, fresh=True)


# ---------------------------------------------------------------- per-user caps
def _spend(pg, uid, n, cost):
    for _ in range(n):
        pg.execute("INSERT INTO ai_calls(id,at,user_id,feature,cost_usd) VALUES(%s,%s,%s,'chat',%s)",
                   (uuid.uuid4().hex, time.time(), uid, cost))
    pg.commit()


def test_caps_stop_a_student_not_the_owner(mu, pg, monkeypatch):
    client = mu
    _setup_a(client, pg)
    _act_as(monkeypatch, B)
    client.get("/api/me")
    ua, ub = _uid_of(pg, A), _uid_of(pg, B)
    monkeypatch.setenv("CF_USER_DAILY_USD", "0.50")
    monkeypatch.setenv("CF_USER_DAILY_CALLS", "0")
    _spend(pg, ub, 3, 0.20)
    _spend(pg, ua, 10, 5.0)
    assert "budget" in multiuser.over_cap(run.db, ub, B)
    assert multiuser.over_cap(run.db, ua, A) is None                   # the owner is never capped per user
    monkeypatch.setenv("CF_USER_CAPS", "off")
    assert multiuser.over_cap(run.db, ub, B) is None


def test_cap_guard_refuses_the_model_call(mu, pg, monkeypatch):
    client = mu
    _act_as(monkeypatch, B)
    client.get("/api/me")
    ub = _uid_of(pg, B)
    monkeypatch.setenv("CF_USER_DAILY_CALLS", "2")
    _spend(pg, ub, 2, None)
    tok = run._CALL.set({"email": B, "user_id": ub, "path": "/api/x"})
    try:
        with pytest.raises(llm.LimitReached):
            llm.client()
    finally:
        run._CALL.reset(tok)


# ---------------------------------------------------------------- behaviour that needs the protected patch
@needs_patch
def test_b_can_open_the_games_on_as_course_but_not_drafts(mu, pg, monkeypatch):
    client = mu
    cid, _, _ = _setup_a(client, pg)
    pg.execute("INSERT INTO docket_games(id,course_id,title,status,game,created) VALUES('g-draft',%s,'Draft','draft','{}'::jsonb,%s)",
               (cid, time.time()))
    pg.commit()
    _act_as(monkeypatch, B)
    r = client.get(f"/api/courses/{cid}/docket?draft=g-draft")
    assert r.status_code == 200 and all(g["id"] != "g-draft" for g in r.json())
    assert client.get(f"/api/courses/{cid}/docket/g-draft").status_code == 404
    assert client.get(f"/api/courses/{cid}/docket-drafts").status_code == 404   # authoring stays owner-only


@needs_patch
def test_spend_and_usage_never_show_other_users(mu, pg, monkeypatch):
    client = mu
    cid, _, _ = _setup_a(client, pg)
    ua = _uid_of(pg, A)
    _spend(pg, ua, 4, 1.0)
    assert client.get("/api/spend/week").json()["calls"] == 4             # the owner sees the app
    _act_as(monkeypatch, B)
    assert client.get("/api/spend/week").json()["calls"] == 0             # B sees only B
    u = client.get(f"/api/courses/{cid}/usage").json()
    assert u["messages"] == 0 and u["sessions"] == 0 and u["cards"] == 1


@needs_patch
def test_an_invite_admits_with_auth_on(mu, pg):
    import auth
    mu.post("/api/admin/invites", json={"email": "invitee@example.com"})
    assert auth.admitted("invitee@example.com", run.db)
    assert not auth.admitted("stranger@example.com", run.db)
    mu.delete("/api/admin/invites/invitee@example.com")
    assert not auth.admitted("invitee@example.com", run.db)


@needs_patch
def test_a_capped_student_gets_429(mu, pg, monkeypatch):
    client = mu
    _act_as(monkeypatch, B)
    client.get("/api/me")
    ub = _uid_of(pg, B)
    monkeypatch.setenv("CF_USER_DAILY_CALLS", "1")
    _spend(pg, ub, 1, None)
    from fastapi import HTTPException
    tok = run._CALL.set({"email": B, "user_id": ub, "path": "/api/x"})
    try:
        with pytest.raises(HTTPException) as e:
            run.client()
        assert e.value.status_code == 429
    finally:
        run._CALL.reset(tok)


@needs_patch
def test_streak_freeze_ledger_is_per_user(mu, pg, monkeypatch):
    client = mu
    cid, _, _ = _setup_a(client, pg)
    ua = _uid_of(pg, A)
    pg.execute("INSERT INTO streak_freezes(course_id,user_id,day,created) VALUES(%s,%s,'2026-01-01',%s)", (cid, ua, time.time()))
    pg.commit()
    _act_as(monkeypatch, B)
    client.get(f"/api/courses/{cid}/stats")
    ub = _uid_of(pg, B)
    pg.execute("INSERT INTO streak_freezes(course_id,user_id,day,created) VALUES(%s,%s,'2026-01-01',%s)", (cid, ub, time.time()))
    pg.commit()   # same course + day, different user: allowed now
    assert pg.execute("SELECT COUNT(*) FROM streak_freezes WHERE course_id=%s", (cid,)).fetchone()[0] == 2
