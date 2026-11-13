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
    """Add the routes and register the per-user cap guard. Idempotent (tests may call it on run.app)."""
    _STATE["db"], _STATE["call"] = db, call_ctx
    if not getattr(app.state, "multiuser_installed", False):
        app.include_router(router)
        app.state.multiuser_installed = True
    if cap_guard not in llm.GUARDS:
        llm.GUARDS.append(cap_guard)


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


def invited_emails(db=None, fresh: bool = False) -> frozenset:
    """Live (not revoked) invited addresses. Cached for INVITE_TTL seconds: auth re-checks admission on EVERY request,
    and a database round trip per request is not worth it. A revoke takes effect within that window."""
    now = time.time()
    if fresh or now - _INVITED["at"] > INVITE_TTL:
        try:
            with (db or _db())() as d:
                got = frozenset(r["email"] for r in d.execute("SELECT email FROM invites WHERE revoked IS NULL").fetchall())
        except Exception:      # noqa: BLE001 - a DB blip must not lock the owner out; ALLOWED_EMAILS still applies
            return _INVITED["emails"]
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
        out["owned_course_content"] = {
            cid: {"notes": d.execute("SELECT id,title,body,updated FROM notes WHERE course_id=?", (cid,)).fetchall(),
                  "cards": d.execute("SELECT id,front,back,source,week,created FROM cards WHERE course_id=?", (cid,)).fetchall(),
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
        if email:
            d.execute("UPDATE invites SET revoked=? WHERE email=? AND revoked IS NULL", (time.time(), email["email"]))
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
