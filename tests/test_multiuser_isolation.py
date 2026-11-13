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


def _act_as(monkeypatch, email, ack=True):
    """Switch the acting user. A non-owner also acknowledges the privacy notice (the patched app refuses every other
    /api route with 428 until they have), unless ack=False."""
    monkeypatch.setenv("ALLOWED_EMAILS", f"{email},{A}" if email != A else A)
    if ack and email != A:
        from fastapi.testclient import TestClient
        assert TestClient(run.app).put("/api/me/privacy", json={"privacy_ack": True}).status_code == 200


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
    tok = run._CALL.set({"email": B, "user_id": ub, "path": "/api/x"})
    try:
        with pytest.raises(llm.LimitReached):   # passes through the broad handlers that re-raise it...
            run.client()
    finally:
        run._CALL.reset(tok)
    r = client.post("/api/speech", json={"question": "Q?", "answer": "A."})   # ...and is a 429 at the edge
    assert r.status_code == 429 and "limit" in r.json()["detail"].lower()


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


# ---------------------------------------------------------------- 2026-11-14 fixes (all need the protected patch)
import json
import threading
from unittest import mock

C = "third@example.com"
CANARY = "CANARY-grader-note-about-B-7f3a"


def _bench(payload):
    msg = mock.MagicMock()
    msg.content = [mock.MagicMock(type="text", text=json.dumps(payload))]
    msg.usage = None
    fake = mock.MagicMock()
    fake.messages.create.return_value = msg
    return fake


def _fill(path, ids):
    import re as _re
    return _re.sub(r"\{([a-z_]+)\}", lambda m: ids.get(m.group(1), "nope"), path)


def _sweep(client, ids):
    """GET every parameterless-or-fillable GET route as the current user; return the concatenated bodies."""
    from starlette.routing import Route
    seen = []
    quiet = _bench([])
    with mock.patch.object(run, "client", return_value=quiet):
        for r in run.app.routes:
            if not isinstance(r, Route) or "GET" not in (r.methods or ()) or not r.path.startswith("/api/"):
                continue
            if any(x in r.path for x in ("/raw", "/audio/file", "/audio", "/export")):
                continue   # binary/stream bodies; export is covered by its own test
            try:
                resp = client.get(_fill(r.path, ids))
                seen.append(resp.text)
            except Exception:   # noqa: BLE001 - a route that cannot run here proves nothing either way
                continue
    return "\n".join(seen)


@needs_patch
def test_bs_missed_bench_note_is_bs_private_card_never_in_as_deck(mu, pg, monkeypatch):
    """LEAK (1): B's missed bench question used to add a card with the grader's note on B's answer to A's SHARED deck."""
    client = mu
    cid, kid, _ = _setup_a(client, pg)
    before = len(client.get(f"/api/courses/{cid}/cards").json())
    _act_as(monkeypatch, B)
    with mock.patch.object(run, "client", return_value=_bench(
            {"mastery": "missed", "verdict": "No", "spoken": "Not yet.", "note": CANARY})):
        r = client.post(f"/api/courses/{cid}/court/reply", json={"case": "Dassonville", "question": "Q-court?", "answer": "x"})
    assert r.status_code == 200, r.text
    ub = _uid_of(pg, B)
    row = pg.execute("SELECT id, user_id FROM cards WHERE back=%s", (CANARY,)).fetchone()
    assert row and row[1] == ub                                           # a PRIVATE card, B's
    assert CANARY in client.get(f"/api/courses/{cid}/cards").text         # B practises it
    assert client.get(f"/api/courses/{cid}/stats").json()["cards"] == before + 1

    _act_as(monkeypatch, A)
    assert len(client.get(f"/api/courses/{cid}/cards").json()) == before  # A's deck did not grow
    assert client.get(f"/api/courses/{cid}/usage").json()["cards"] == before
    assert client.put(f"/api/cards/{row[0]}", json={"front": "x"}).status_code == 404
    body = _sweep(client, {"cid": cid, "kid": row[0], "nid": "nope"})
    assert CANARY not in body                                             # nowhere A can read
    assert CANARY not in json.dumps(client.get("/api/me/export").json())

    _act_as(monkeypatch, C)
    assert CANARY not in _sweep(client, {"cid": cid, "kid": row[0]})      # nor a third student

    _act_as(monkeypatch, B)
    assert client.post("/api/me/delete", json={"confirm": B}).status_code == 200
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE back=%s", (CANARY,)).fetchone()[0] == 0   # erased with B


@needs_patch
def test_bs_missed_case_mcq_is_private_and_dedupes_per_user(mu, pg, monkeypatch):
    client = mu
    cid, _, _ = _setup_a(client, pg)
    pg.execute("INSERT INTO case_hypos(id,course_id,week,length,facts,source,thin,created) VALUES('h1',%s,'','short','F',"
               "'s',0,%s)", (cid, time.time()))
    pg.execute("INSERT INTO case_hypo_mcqs(id,case_id,course_id,ord,question,options,correct_index,explanation,concept,created) "
               "VALUES('m1','h1',%s,0,'Which?','[\"a\",\"b\"]'::jsonb,0,'because','c',%s)", (cid, time.time()))
    pg.commit()
    a_before = len(client.get(f"/api/courses/{cid}/cards").json())
    _act_as(monkeypatch, B)
    for _ in range(2):
        assert client.post(f"/api/courses/{cid}/case/answer", json={"qid": "m1", "selected_index": 1}).status_code == 200
    ub = _uid_of(pg, B)
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE source='case:h1' AND user_id=%s", (ub,)).fetchone()[0] == 1
    _act_as(monkeypatch, A)
    assert len(client.get(f"/api/courses/{cid}/cards").json()) == a_before
    client.post(f"/api/courses/{cid}/case/answer", json={"qid": "m1", "selected_index": 1})   # A's own miss: shared
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE source='case:h1' AND user_id IS NULL").fetchone()[0] == 1


@needs_patch
def test_case_rotation_is_per_user(mu, pg, monkeypatch):
    client = mu
    cid, _, _ = _setup_a(client, pg)
    for i, h in enumerate(("h1", "h2")):
        pg.execute("INSERT INTO case_hypos(id,course_id,week,length,facts,source,thin,created) VALUES(%s,%s,'','short','F',"
                   "'s',0,%s)", (h, cid, time.time() + i))
        pg.execute("INSERT INTO case_hypo_mcqs(id,case_id,course_id,ord,question,options,correct_index,explanation,concept,created) "
                   "VALUES(%s,%s,%s,0,'Which?','[\"a\",\"b\"]'::jsonb,0,'because','c',%s)", ("m" + h, h, cid, time.time()))
    pg.commit()
    first = client.post(f"/api/courses/{cid}/case/next", json={}).json()["case"]["id"]
    _act_as(monkeypatch, B)
    assert client.post(f"/api/courses/{cid}/case/next", json={}).json()["case"]["id"] == first   # A's practice is not B's


@needs_patch
def test_delete_then_sign_in_again_is_capped_and_logged_to_the_new_id(mu, pg, monkeypatch):
    """LEAK (2): the email->id cache kept the erased id, so the re-created account was never capped."""
    client = mu
    _act_as(monkeypatch, B)
    old = _uid_of(pg, B)
    tok = run._CALL.set({"email": B, "user_id": None, "path": "/api/x"})   # what call_context sets under a session
    try:
        llm._emit({"task": "chat", "provider": "t", "model": "m", "in": 1, "out": 1, "cost": None})
    finally:
        run._CALL.reset(tok)
    assert client.post("/api/me/delete", json={"confirm": B}).status_code == 200
    _act_as(monkeypatch, B)                                               # signs in again: a fresh account
    new = _uid_of(pg, B)
    assert new and new != old
    monkeypatch.setenv("CF_USER_DAILY_CALLS", "1")
    tok = run._CALL.set({"email": B, "user_id": None, "path": "/api/x"})
    try:
        llm._emit({"task": "chat", "provider": "t", "model": "m", "in": 1, "out": 1, "cost": None})
    finally:
        run._CALL.reset(tok)
    assert pg.execute("SELECT COUNT(*) FROM ai_calls WHERE user_id=%s", (new,)).fetchone()[0] == 1
    assert client.post("/api/speech", json={"question": "Q?", "answer": "A."}).status_code == 429


@needs_patch
def test_privacy_ack_is_enforced_before_first_use(mu, pg, monkeypatch):
    client = mu
    cid, _, _ = _setup_a(client, pg)
    _act_as(monkeypatch, B, ack=False)
    assert client.get("/api/me").json()["privacy"]["privacy_ack"] is None
    r = client.get(f"/api/courses/{cid}/cards")
    assert r.status_code == 428 and "privacy" in r.json()["detail"]
    assert client.get("/api/courses").status_code == 428
    assert client.get("/api/me/export").status_code == 200                # leaving is always possible
    assert client.put("/api/me/privacy", json={"privacy_ack": True}).status_code == 200
    assert client.get(f"/api/courses/{cid}/cards").status_code == 200
    _act_as(monkeypatch, A)
    assert client.get(f"/api/courses/{cid}/cards").status_code == 200     # the owner is never asked


def test_main_ui_links_account_and_privacy_and_gates_on_ack():
    from pathlib import Path
    root = Path(run.__file__).parent / "static"
    html, js = (root / "index.html").read_text(), (root / "app.js").read_text()
    assert 'href="/static/account.html"' in html and 'href="/static/privacy.html"' in html
    assert "privacy_ack" in js and "/static/account.html?ack=1" in js
    acct = (root / "account.html").read_text()
    assert 'id="ack"' in acct and "privacy_ack: true" in acct


@needs_patch
def test_a_students_own_course_is_private_to_them(mu, pg, monkeypatch):
    """(7) Files, notes and versions in a course a STUDENT creates are no longer readable by every signed-in user."""
    client = mu
    _setup_a(client, pg)
    _act_as(monkeypatch, B)
    bcid = client.post("/api/courses", json={"name": "B private"}).json()["id"]
    nid = client.post(f"/api/courses/{bcid}/notes", json={"title": "B note", "body": "B-SECRET-BODY"}).json()["id"]
    fid = client.post(f"/api/courses/{bcid}/files", files={"file": ("b.txt", b"B-SECRET-FILE " * 50, "text/plain")}).json()["id"]
    assert "B-SECRET-BODY" in client.get(f"/api/notes/{nid}").text
    assert any(c["id"] == bcid and c["mine"] and "user_id" not in c for c in client.get("/api/courses").json())   # S8

    for who in (C, A):
        _act_as(monkeypatch, who)
        assert all(c["id"] != bcid for c in client.get("/api/courses").json()), who
        for path in (f"/api/courses/{bcid}/files", f"/api/courses/{bcid}/notes", f"/api/notes/{nid}",
                     f"/api/notes/{nid}/versions", f"/api/files/{fid}/text", f"/api/files/{fid}/raw",
                     f"/api/courses/{bcid}/cards", f"/api/courses/{bcid}/search?q=SECRET"):
            assert client.get(path).status_code == 404, (who, path)
        assert bcid not in client.get("/api/due").json()
        assert all(c["id"] != bcid for c in client.get("/api/today").json().get("courses", []))
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/voice/dialog?course={bcid}") as ws:
                ws.receive_text()

    _act_as(monkeypatch, B)
    assert client.get(f"/api/courses/{bcid}/files").status_code == 200


@needs_patch
def test_capture_rows_carry_the_user_and_are_erased_with_them(mu, pg, monkeypatch):
    """(6) card_gen_samples / card_edits had no user_id, so they survived account deletion and were not exported."""
    client = mu
    _setup_a(client, pg)
    _act_as(monkeypatch, B)
    client.put("/api/me/privacy", json={"capture_consent": True})
    ub = _uid_of(pg, B)
    tok = run._CALL.set({"email": B, "user_id": ub, "path": "/api/x"})
    try:
        run._capture_card_sample("gs-b", "c", __import__("types").SimpleNamespace(model="m", usage=None), "file", "1", 1, 1, "src", [{"front": "f", "back": "b"}], False, False)
        run._capture_card_edit("k", "gs-b", "c", "f", "b", "f2", "b2")
    finally:
        run._CALL.reset(tok)
    assert pg.execute("SELECT user_id FROM card_gen_samples WHERE id='gs-b'").fetchone()[0] == ub
    assert pg.execute("SELECT COUNT(*) FROM card_edits WHERE user_id=%s", (ub,)).fetchone()[0] == 1
    exp = client.get("/api/me/export").json()["tables"]
    assert [r["id"] for r in exp["card_gen_samples"]] == ["gs-b"] and len(exp["card_edits"]) == 1
    erased = client.post("/api/me/delete", json={"confirm": B}).json()["erased"]
    assert erased["card_gen_samples"] == 1 and erased["card_edits"] == 1
    for t in ("card_gen_samples", "card_edits"):
        assert pg.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=%s", (ub,)).fetchone()[0] == 0


@needs_patch
def test_bulk_card_and_local_lanes_are_capped(mu, pg, monkeypatch):
    """(5) gateway.call and llm.local_call never reached client(), so the cheap bulk lane ignored the per-user cap."""
    import gateway
    client = mu
    _act_as(monkeypatch, B)
    ub = _uid_of(pg, B)
    monkeypatch.setenv("CF_USER_DAILY_CALLS", "1")
    _spend(pg, ub, 1, None)
    monkeypatch.setattr(gateway, "allows", lambda task: True)
    monkeypatch.setattr(llm, "local_allows", lambda task: True)
    tok = run._CALL.set({"email": B, "user_id": ub, "path": "/api/x"})
    try:
        with pytest.raises(llm.LimitReached):
            gateway.call("cards", max_tokens=10, messages=[{"role": "user", "content": "x"}])
        with pytest.raises(llm.LimitReached):
            llm.local_call("cards", max_tokens=10, messages=[{"role": "user", "content": "x"}])
        with pytest.raises(llm.LimitReached):
            run.ask_model(run.CHEAP_MODEL, task="cards", max_tokens=10, messages=[{"role": "user", "content": "x"}])
    finally:
        run._CALL.reset(tok)


@needs_patch
def test_background_jobs_keep_the_requesting_user(mu, pg, monkeypatch):
    """(5) a thread started by a request used to lose the call context: uncapped, and logged with user_id NULL."""
    client = mu
    _act_as(monkeypatch, B)
    bcid = client.post("/api/courses", json={"name": "B course"}).json()["id"]
    nid = client.post(f"/api/courses/{bcid}/notes", json={"title": "N", "body": "Some text to read aloud."}).json()["id"]
    got, done = {}, threading.Event()
    def fake_make(jid, nid_, fp):
        got.update(run._CALL.get() or {}); done.set()
    monkeypatch.setattr(run, "_make_note_audio", fake_make)
    monkeypatch.setattr(run.tts, "available", lambda: True)
    assert client.post(f"/api/notes/{nid}/audio").status_code == 200
    assert done.wait(10) and got.get("email") == B
    assert pg.execute("SELECT COUNT(*) FROM ai_calls WHERE feature='note-audio' AND user_id=%s", (_uid_of(pg, B),)).fetchone()[0] == 1


@needs_patch
def test_server_voice_is_metered_and_capped(mu, pg, monkeypatch):
    client = mu
    _act_as(monkeypatch, B)
    ub = _uid_of(pg, B)
    monkeypatch.setattr(run.tts, "available", lambda: True)
    monkeypatch.setattr(run.tts, "say", lambda text, voice=None: (b"ID3", "audio/mpeg"))
    assert client.post("/api/speak", json={"text": "hello"}).status_code == 200
    assert pg.execute("SELECT COUNT(*) FROM ai_calls WHERE feature='speak' AND user_id=%s", (ub,)).fetchone()[0] == 1
    monkeypatch.setenv("CF_USER_DAILY_CALLS", "1")
    assert client.post("/api/speak", json={"text": "hello"}).status_code == 429
    with pytest.raises(Exception):   # the voice socket closes before accepting (4429)
        with client.websocket_connect("/api/voice/dialog") as ws:
            ws.receive_text()
    _act_as(monkeypatch, A)
    assert client.post("/api/speak", json={"text": "hello"}).status_code == 200   # the owner is never capped


@needs_patch
def test_erase_drops_the_invite_and_the_owner_can_erase_an_account(mu, pg, monkeypatch):
    client = mu
    _setup_a(client, pg)
    client.post("/api/admin/invites", json={"email": B})
    _act_as(monkeypatch, B)
    ub = _uid_of(pg, B)
    _act_as(monkeypatch, A)
    assert client.post(f"/api/admin/users/{ub}/delete", json={"confirm": "wrong@x.com"}).status_code == 422
    assert client.post(f"/api/admin/users/{_uid_of(pg, A)}/delete", json={"confirm": A}).status_code == 403
    r = client.post(f"/api/admin/users/{ub}/delete", json={"confirm": B})
    assert r.status_code == 200 and r.json()["erased"]["invites"] == 1
    assert pg.execute("SELECT COUNT(*) FROM invites WHERE email=%s", (B,)).fetchone()[0] == 0   # S11
    assert pg.execute("SELECT COUNT(*) FROM users WHERE id=%s", (ub,)).fetchone()[0] == 0
    _act_as(monkeypatch, B, ack=False)
    assert client.post(f"/api/admin/users/{_uid_of(pg, A)}/delete", json={"confirm": A}).status_code in (403, 428)


def test_invite_lookup_does_not_retry_every_request_during_an_outage(monkeypatch):
    """C1: a DB outage used to re-query on every request (auth checks admission on every request)."""
    calls = []
    def broken():
        calls.append(1); raise RuntimeError("db down")
    multiuser._INVITED.update(at=0.0, emails=frozenset({"kept@example.com"}))
    assert multiuser.invited_emails(broken) == frozenset({"kept@example.com"})
    assert multiuser.invited_emails(broken) == frozenset({"kept@example.com"})
    assert len(calls) == 1
    multiuser._INVITED.update(at=0.0, emails=frozenset())
