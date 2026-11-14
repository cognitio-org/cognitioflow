"""
Multi-user readiness: invites, privacy (notice, export, delete, consent) and per-user AI caps.

Everything here lives OUTSIDE the protected files. It is wired in by ONE line in run.py
(`multiuser.install(app, db, _CALL)`, see docs/multi-user/protected-changes.patch) and, for invites to admit anyone,
one change in auth.py. Until that patch is applied nothing in this module runs in production.

Ownership model (#178): course CONTENT is shared and owner-edited; PROGRESS is private per user. This module never
widens what one user can read about another. Every /api/me route acts only on the caller's own rows; every
/api/admin route is the owner's signed-in session only (auth._owner: never an API key).

  GET    /api/me                  who am I, owner?, my privacy settings, my AI use today and my caps
  GET    /api/me/export           every row that is mine (Art. 15 / Art. 20), as one JSON download
  PUT    /api/me/privacy          {capture_consent: bool, privacy_ack: bool}
  POST   /api/me/delete           {confirm: "<my email>"} erases my progress and my account (Art. 17)
  GET    /api/admin/invites       owner: invited addresses
  POST   /api/admin/invites       owner: {email, note} records an invite. NOTHING is sent; the owner shares the link.
  DELETE /api/admin/invites/{e}   owner: revoke
  GET    /api/admin/users         owner: accounts with their 24h / 30d AI cost (counts only, never content)

Also enforced here, for every user but the owner (PrivacyGate, the innermost middleware):
  - the privacy notice must be acknowledged (PUT /api/me/privacy {privacy_ack: true}) before any other /api route: 428
  - a course a STUDENT created is private to that student: its files, notes, versions, recordings, cards and concepts
    are 404 to every other signed-in user, and it is left out of their course list (run.py patch). Courses the owner
    created (or unowned seeds) stay read-shared as in #178.
  - a per-user daily AI cap (CF_USER_DAILY_USD / CF_USER_DAILY_CALLS) on the model lanes (client(), the gateway bulk
    lane, the local lane) and on metered voice/speech/STT/TTS uses (meter()); a refusal is HTTP 429 everywhere.
    The cap is check-then-log: concurrent calls can overshoot it by at most the calls already in flight.
"""
import os
import re
import time
from contextvars import ContextVar
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import auth
import llm

EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
# Progress rows erased first, in FK-safe order; any other table with a user_id is found from the schema afterwards.
_ERASE_FIRST = ("essay_revisions", "essay_attempts", "reviews", "messages", "sessions", "streak_freezes", "card_state")
_KEEP_ANONYMISED = ("ai_calls",)          # the cost log keeps its counts; the row just stops pointing at the person
_NEVER_EXPORT_COLS = {"hash"}             # api_tokens.hash: a credential digest is not personal data worth handing out

router = APIRouter()
_STATE = {"db": None, "call": None}


# ---------------------------------------------------------------- wiring
def install(app, db, call_ctx: Optional[ContextVar] = None) -> None:
    """Add the routes, the 429 handler, the privacy gate, and register the per-user cap guard. Idempotent (tests may
    call it on run.app). Call it BEFORE the first request: the gate is appended as the innermost middleware (inside
    auth, so it sees request.state.user), and Starlette builds its middleware stack once, on the first request."""
    _STATE["db"], _STATE["call"] = db, call_ctx
    if not getattr(app.state, "multiuser_installed", False):
        app.include_router(router)
        app.state.multiuser_installed = True
    rebuild = False
    if llm.LimitReached not in app.exception_handlers:   # also after a test reloads llm (a new LimitReached class)
        app.add_exception_handler(llm.LimitReached, _limit_reached)
        rebuild = True
    if not any(m.cls is PrivacyGate for m in app.user_middleware):
        from starlette.middleware import Middleware
        app.user_middleware.append(Middleware(PrivacyGate))
        rebuild = True
    if rebuild and getattr(app, "middleware_stack", None) is not None:
        app.middleware_stack = None   # already served a request (tests only): Starlette rebuilds it on the next call
    if cap_guard not in llm.GUARDS:
        llm.GUARDS.append(cap_guard)


async def _limit_reached(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=429)


def _db(request: Optional[Request] = None):
    if request is not None:
        return request.app.state.db
    if _STATE["db"] is None:
        raise RuntimeError("multiuser.install() was not called")
    return _STATE["db"]


def is_owner(user: dict) -> bool:
    return str(user.get("email", "")).lower() == auth.owner_email()


# ---------------------------------------------------------------- invites (read by the auth.py patch)
_INVITED: dict = {"at": 0.0, "emails": frozenset()}
INVITE_TTL = float(os.environ.get("CF_INVITE_CACHE_S", "30"))
INVITE_RETRY_S = 5.0


def invited_emails(db=None, fresh: bool = False) -> frozenset:
    """Live (not revoked) invited addresses. Cached for INVITE_TTL seconds: auth re-checks admission on EVERY request,
    and a database round trip per request is not worth it. A revoke takes effect within that window."""
    now = time.time()
    if fresh or now - _INVITED["at"] > INVITE_TTL:
        try:
            with (db or _db())() as d:
                got = frozenset(r["email"] for r in d.execute("SELECT email FROM invites WHERE revoked IS NULL").fetchall())
        except Exception:      # noqa: BLE001 - a DB blip must not lock the owner out; ALLOWED_EMAILS still applies
            _INVITED["at"] = now - INVITE_TTL + INVITE_RETRY_S   # C1: keep the last list, retry in a few seconds,
            return _INVITED["emails"]                           # not on every request of an outage
        _INVITED.update(at=now, emails=got)
    return _INVITED["emails"]


def mark_accepted(db, email: str) -> None:
    with db() as d:
        d.execute("UPDATE invites SET accepted=? WHERE email=? AND accepted IS NULL", (time.time(), email.lower()))


class InviteIn(BaseModel):
    email: str
    note: str = ""


@router.get("/api/admin/invites")
def list_invites(request: Request):
    auth._owner(request)
    with _db(request)() as d:
        return d.execute("SELECT email,note,created,revoked,accepted FROM invites ORDER BY created DESC").fetchall()


@router.post("/api/admin/invites")
def add_invite(p: InviteIn, request: Request):
    """Records the address only. Nothing is emailed: the owner sends the link himself (no mail is ever sent from here)."""
    user = auth._owner(request)
    email = p.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "That is not an email address.")
    with _db(request)() as d:
        d.execute("INSERT INTO invites(email,invited_by,note,created) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE "
                  "SET revoked=NULL, note=EXCLUDED.note", (email, user["id"], p.note.strip()[:200], time.time()))
    invited_emails(_db(request), fresh=True)
    return {"ok": True, "email": email, "link": "https://cognitioflow.ai/",
            "next": "Send them the link yourself. They sign in with Google using exactly this address."}


@router.delete("/api/admin/invites/{email}")
def revoke_invite(email: str, request: Request):
    auth._owner(request)
    with _db(request)() as d:
        d.execute("UPDATE invites SET revoked=? WHERE email=? AND revoked IS NULL", (time.time(), email.strip().lower()))
    invited_emails(_db(request), fresh=True)
    return {"ok": True}


@router.get("/api/admin/users")
def list_users(request: Request):
    auth._owner(request)
    day, month = time.time() - 86400, time.time() - 30 * 86400
    with _db(request)() as d:
        users = d.execute(
            "SELECT u.id,u.email,u.created,"
            " COALESCE((SELECT SUM(cost_usd) FROM ai_calls a WHERE a.user_id=u.id AND a.at>=?),0) AS cost_24h,"
            " COALESCE((SELECT SUM(cost_usd) FROM ai_calls a WHERE a.user_id=u.id AND a.at>=?),0) AS cost_30d,"
            " (SELECT COUNT(*) FROM ai_calls a WHERE a.user_id=u.id AND a.at>=?) AS calls_24h "
            "FROM users u ORDER BY u.created", (day, month, day)).fetchall()
    return [{**u, "cost_24h": round(float(u["cost_24h"]), 4), "cost_30d": round(float(u["cost_30d"]), 4)} for u in users]


# ---------------------------------------------------------------- per-user AI caps
def caps() -> dict:
    """CF_USER_DAILY_USD / CF_USER_DAILY_CALLS. 0 switches that cap off. The owner is never capped (the app-wide
    CF_GATEWAY_SPEND_CEILING still applies to everyone)."""
    def num(name, default):
        try: return float(os.environ.get(name, default))
        except ValueError: return float(default)
    return {"daily_usd": num("CF_USER_DAILY_USD", "1.00"), "daily_calls": int(num("CF_USER_DAILY_CALLS", "150"))}


def usage_today(db, uid: str) -> dict:
    with db() as d:
        r = d.execute("SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS cost FROM ai_calls WHERE user_id=? AND at>=?",
                      (uid, time.time() - 86400)).fetchone()
    return {"calls": int(r["calls"]), "cost": round(float(r["cost"]), 4)}


def over_cap(db, uid: Optional[str], email: str) -> Optional[str]:
    """The reason this user may not make another AI call right now, or None."""
    if not uid or os.environ.get("CF_USER_CAPS", "on").lower() == "off" or email.lower() == auth.owner_email():
        return None
    c, u = caps(), usage_today(db, uid)
    if c["daily_calls"] and u["calls"] >= c["daily_calls"]:
        return f"Daily AI limit reached ({c['daily_calls']} calls in 24 hours). It resets on a rolling basis."
    if c["daily_usd"] and u["cost"] >= c["daily_usd"]:
        return f"Daily AI budget reached (${c['daily_usd']:.2f} in 24 hours). It resets on a rolling basis."
    return None


def _ctx_user(user: Optional[dict] = None) -> tuple:
    """(uid, email) of the acting user: the given user dict (a websocket's scope user), else the request context."""
    ctx = user if user is not None else (_STATE["call"].get() if _STATE["call"] else None)
    if not ctx or _STATE["db"] is None:
        return None, ""
    uid, email = ctx.get("user_id") or ctx.get("id"), (ctx.get("email") or "")
    if not uid and email:
        with _STATE["db"]() as d:
            r = d.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()
        uid = r["id"] if r else None
    return uid, email


def meter(feature: str, user: Optional[dict] = None) -> None:
    """A metered AI use that never goes through llm.usage() (server TTS, hosted STT, a voice session): refuse it over
    the cap (LimitReached -> 429), else log one ai_calls row (cost unknown, so it counts toward the CALLS cap)."""
    uid, email = _ctx_user(user)
    if not email:
        return                        # no user (a script): the app-wide ceilings still apply
    why = over_cap(_STATE["db"], uid, email)
    if why:
        raise llm.LimitReached(why)
    tok = _STATE["call"].set({"email": email, "user_id": uid, "path": feature}) if _STATE["call"] and user is not None else None
    try:
        llm._emit({"task": feature, "provider": "voice", "model": feature, "in": 0, "out": 0, "cost": None})
    finally:
        if tok is not None:
            _STATE["call"].reset(tok)


def cap_guard() -> None:
    """Registered in llm.GUARDS: runs before every client() is built, i.e. before any main-path model call. Raises
    llm.LimitReached (a ConfigError, so run.client() already turns it into an HTTP error instead of a 500)."""
    ctx = _STATE["call"].get() if _STATE["call"] else None
    if not ctx or _STATE["db"] is None:
        return                       # background jobs and scripts have no request user: not capped here
    uid, email = ctx.get("user_id"), ctx.get("email") or ""
    if not uid and email:
        with _STATE["db"]() as d:
            r = d.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()
        uid = r["id"] if r else None
    why = over_cap(_STATE["db"], uid, email)
    if why:
        raise llm.LimitReached(why)


# ---------------------------------------------------------------- private student courses (default private)
#: SQL fragment on a `c.course_id` column: the courses this user may READ. TWO args: the caller's uid, then the owner's
#: email (auth.owner_email()). Owner-created and unowned (seeded) courses are read-shared (#178); a course anyone else
#: created is private to its creator.
SEE_COURSE_SQL = ("c.course_id IN (SELECT co.id FROM courses co LEFT JOIN users ou ON ou.id=co.user_id "
                  "WHERE co.user_id IS NULL OR co.user_id=? OR lower(ou.email)=?)")
COURSE_ROW_SQL = ("(courses.user_id IS NULL OR courses.user_id=? OR courses.user_id IN "
                  "(SELECT id FROM users WHERE lower(email)=?))")   # same rule, on a `courses` row; same two args


def course_private_to(db, cid: str) -> Optional[str]:
    """The creator's uid when the course is private (created by someone other than the app owner), else None."""
    with db() as d:
        r = d.execute("SELECT co.user_id AS uid, lower(u.email) AS email FROM courses co LEFT JOIN users u ON u.id=co.user_id "
                      "WHERE co.id=?", (cid,)).fetchone()
    if not r or not r["uid"] or r["email"] == auth.owner_email():
        return None
    return r["uid"]


def can_see_course(db, cid: str, uid: Optional[str]) -> bool:
    owner = course_private_to(db, cid)
    return owner is None or owner == uid


_SUB = (   # by-id routes -> the course the row belongs to
    (re.compile(r"^/api/courses/([^/]+)"), None),
    (re.compile(r"^/api/notes/([^/]+)"), "SELECT course_id FROM notes WHERE id=?"),
    (re.compile(r"^/api/files/([^/]+)"), "SELECT course_id FROM files WHERE id=?"),
    (re.compile(r"^/api/cards/([^/]+)"), "SELECT course_id FROM cards WHERE id=?"),
    (re.compile(r"^/api/concepts/([^/]+)"), "SELECT course_id FROM concepts WHERE id=?"),
    (re.compile(r"^/api/recordings/([^/]+)"), "SELECT n.course_id AS course_id FROM recordings r JOIN notes n ON n.id=r.note_id WHERE r.id=?"),
    (re.compile(r"^/api/versions/([^/]+)"), "SELECT n.course_id AS course_id FROM note_versions v JOIN notes n ON n.id=v.note_id WHERE v.id=?"),
)
#: Reachable before the privacy notice is acknowledged: who am I, the ack itself, and leaving (export / delete).
ACK_FREE = ("/api/me", "/api/me/privacy", "/api/me/export", "/api/me/delete", "/api/config")


# Signed-in paths outside /api/ that do no per-user work, so the acknowledgement gate lets them through: the app
# shell (it redirects an unacknowledged student to the notice itself), static files, sign-in, health. Every other
# path is gated, so a new non-/api alias (like POST /speech for /api/speech) cannot slip past the notice.
UNGATED_EXACT = ("/", "/sw.js", "/health", "/healthz", "/favicon.ico", "/manifest.json", "/robots.txt")
UNGATED_PREFIX = ("/static/", "/play/", "/auth/")


def gated_path(path: str) -> bool:
    """Does PrivacyGate check this path? Default yes: only the listed shell/static/sign-in/health paths are exempt."""
    return path not in UNGATED_EXACT and not path.startswith(UNGATED_PREFIX)


def course_of_path(db, path: str) -> Optional[str]:
    for rx, sql in _SUB:
        m = rx.match(path)
        if m:
            if sql is None:
                return m.group(1)
            with db() as d:
                r = d.execute(sql, (m.group(1),)).fetchone()
            return r["course_id"] if r else None
    return None


def gate_refusal(db, user: dict, path: str) -> Optional[tuple]:
    """(status, detail) when this signed-in user may not make this /api request, else None. The owner is never asked
    for the acknowledgement, but a student's private course is private from the owner too."""
    if not user:
        return None
    owner = is_owner(user)
    if owner and not any(rx.match(path) for rx, _ in _SUB):
        return None
    uid = user.get("id")
    if not uid:
        with db() as d:
            r = d.execute("SELECT id FROM users WHERE email=?", (str(user.get("email", "")).lower(),)).fetchone()
        uid = r["id"] if r else None
    if not owner and path not in ACK_FREE and not user.get("scope") and (not uid or not prefs(db, uid)["privacy_ack"]):
        return 428, "privacy_ack_required: read the privacy notice at /static/privacy.html and acknowledge it on /static/account.html."
    cid = course_of_path(db, path)
    if cid and not can_see_course(db, cid, uid):
        return 404, "Not Found"
    return None


def ws_refusal(db, user: dict, course: str) -> Optional[int]:
    """A websocket close code for a voice session this user may not open, else None."""
    if not user:
        return 4401
    uid, _ = _ctx_user(user)
    if course and not can_see_course(db, course, uid):
        return 4404
    if is_owner(user):
        return None
    if not uid or not prefs(db, uid)["privacy_ack"]:
        return 4428
    if over_cap(db, uid, user.get("email", "")):
        return 4429
    return None


class PrivacyGate:
    """Innermost ASGI middleware (inside auth): the privacy-ack and private-course checks of gate_refusal for /api/*
    and every other path gated_path() does not exempt.
    The owner skips the acknowledgement; only his requests on a course/by-id path cost a lookup."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not gated_path(scope["path"]) or _STATE["db"] is None:
            return await self.app(scope, receive, send)
        user = (scope.get("state") or {}).get("user")
        if user:
            import asyncio
            got = await asyncio.to_thread(gate_refusal, _STATE["db"], user, scope["path"])
            if got:
                return await JSONResponse({"detail": got[1]}, status_code=got[0])(scope, receive, send)
        return await self.app(scope, receive, send)


# ---------------------------------------------------------------- privacy: settings, export, delete
def prefs(db, uid: str) -> dict:
    with db() as d:
        r = d.execute("SELECT capture_consent,privacy_ack FROM user_prefs WHERE user_id=?", (uid,)).fetchone()
    return {"capture_consent": None if not r or r["capture_consent"] is None else bool(r["capture_consent"]),
            "privacy_ack": r["privacy_ack"] if r else None}


def capture_allowed(db, uid: Optional[str], email: str = "") -> bool:
    """May the de-identified training capture record this user's material? The owner: yes unless he said no (his
    Phase 19 decision). Anyone else: only after an explicit yes (Art. 6(1)(a), Art. 25 privacy by default)."""
    if not uid:
        return False
    p = prefs(db, uid)["capture_consent"]
    if email and email.lower() == auth.owner_email():
        return p is not False
    return p is True


class PrivacyIn(BaseModel):
    capture_consent: Optional[bool] = None
    privacy_ack: Optional[bool] = None


class DeleteIn(BaseModel):
    confirm: str = ""


def _session_user(request: Request) -> dict:
    user = auth.current_user(request)
    if user.get("scope"):
        raise HTTPException(403, "Keys cannot read or change account data. Sign in instead.")
    return user


@router.get("/api/me")
def me(request: Request, user: dict = Depends(auth.current_user)):
    db = _db(request)
    return {"email": user["email"], "name": user.get("name", ""), "owner": is_owner(user),
            "privacy": prefs(db, user["id"]), "usage_24h": usage_today(db, user["id"]),
            "caps": None if is_owner(user) else caps()}


@router.put("/api/me/privacy")
def set_privacy(p: PrivacyIn, request: Request):
    user = _session_user(request)
    cur = prefs(_db(request), user["id"])
    consent = cur["capture_consent"] if p.capture_consent is None else p.capture_consent
    ack = cur["privacy_ack"] if not p.privacy_ack else time.time()
    with _db(request)() as d:
        d.execute("INSERT INTO user_prefs(user_id,capture_consent,privacy_ack,updated) VALUES(?,?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET capture_consent=EXCLUDED.capture_consent,"
                  "privacy_ack=EXCLUDED.privacy_ack, updated=EXCLUDED.updated",
                  (user["id"], None if consent is None else int(consent), ack, time.time()))
    return prefs(_db(request), user["id"])


def _user_tables(d) -> list:
    got = [r["table_name"] for r in d.execute(
        "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='user_id' "
        "ORDER BY table_name").fetchall()]
    return [t for t in got if _IDENT.match(t)]


def export_user(db, uid: str) -> dict:
    """Every row keyed to this user, plus the content of the courses they own (their own authored material).
    Shared course content owned by someone else is NOT included: it is not theirs."""
    out: dict = {"exported_at": time.time(), "format": "cognitioflow-export-v1", "tables": {}}
    with db() as d:
        out["user"] = d.execute("SELECT id,email,name,created FROM users WHERE id=?", (uid,)).fetchone()
        for t in _user_tables(d):
            rs = d.execute(f'SELECT * FROM "{t}" WHERE user_id=?', (uid,)).fetchall()
            out["tables"][t] = [{k: v for k, v in r.items() if k not in _NEVER_EXPORT_COLS} for r in rs]
        owned = [r["id"] for r in out["tables"].get("courses", [])]
        # Another user's private practice cards (cards.user_id, migration 037) are theirs, not course content. Before
        # 037 is applied there is no such column and every card is course content.
        shared = " AND user_id IS NULL" if "cards" in out["tables"] else ""
        out["owned_course_content"] = {
            cid: {"notes": d.execute("SELECT id,title,body,updated FROM notes WHERE course_id=?", (cid,)).fetchall(),
                  "cards": d.execute("SELECT id,front,back,source,week,created FROM cards WHERE course_id=?" + shared,
                                     (cid,)).fetchall(),
                  "files": d.execute("SELECT id,name,chars FROM files WHERE course_id=?", (cid,)).fetchall()}
            for cid in owned}
    return out


@router.get("/api/me/export")
def export_me(request: Request):
    user = _session_user(request)
    body = export_user(_db(request), user["id"])
    return JSONResponse(body, headers={"Content-Disposition": 'attachment; filename="cognitioflow-my-data.json"'})


def erase_user(db, uid: str) -> dict:
    """Erase one user's progress and account in ONE transaction. Refuses (409) while they own courses: what happens to
    shared content a student authored is the owner's decision, not this function's."""
    counts = {}
    with db() as d:
        if d.execute("SELECT 1 FROM courses WHERE user_id=? LIMIT 1", (uid,)).fetchone():
            raise HTTPException(409, "You own courses. Delete them first (or ask the owner to take them over).")
        tables = _user_tables(d)
        order = [t for t in _ERASE_FIRST if t in tables] + [t for t in tables if t not in _ERASE_FIRST]
        for t in order:
            if t == "courses":
                continue
            if t in _KEEP_ANONYMISED:
                counts[t] = d.execute(f'UPDATE "{t}" SET user_id=NULL WHERE user_id=?', (uid,)).rowcount
            else:
                counts[t] = d.execute(f'DELETE FROM "{t}" WHERE user_id=?', (uid,)).rowcount
        email = d.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
        if email:   # S11: the invite row holds the address; erasure removes it (re-inviting is the owner's choice)
            counts["invites"] = d.execute("DELETE FROM invites WHERE email=?", (email["email"].lower(),)).rowcount
        d.execute("DELETE FROM users WHERE id=?", (uid,))
    _INVITED["at"] = 0.0
    return counts


@router.post("/api/me/delete")
def delete_me(p: DeleteIn, request: Request):
    user = _session_user(request)
    if is_owner(user):
        raise HTTPException(403, "The owner's account cannot be deleted from the app.")
    if p.confirm.strip().lower() != user["email"].lower():
        raise HTTPException(422, "Type your email address to confirm.")
    counts = erase_user(_db(request), user["id"])
    request.session.clear()
    return {"ok": True, "erased": counts,
            "note": "Your account and progress are gone. Signing in again would start a fresh account if you are still invited."}


@router.post("/api/admin/users/{uid}/delete")
def admin_delete_user(uid: str, p: DeleteIn, request: Request):
    """Owner-side erasure (Art. 17 request made to the owner, S5): same erase as /api/me/delete, confirmed by the
    account's email. Never the owner's own account; refused (409) while that user owns courses."""
    auth._owner(request)
    with _db(request)() as d:
        r = d.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        raise HTTPException(404, "No such account.")
    if str(r["email"]).lower() == auth.owner_email():
        raise HTTPException(403, "The owner's account cannot be deleted from the app.")
    if p.confirm.strip().lower() != str(r["email"]).lower():
        raise HTTPException(422, "Type that account's email address to confirm.")
    return {"ok": True, "erased": erase_user(_db(request), uid)}
