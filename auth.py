"""
Google sign-in (Phase 4). The signed session cookie is the only credential: no Bearer/API tokens.

  GET  /auth/login     -> Google OAuth (authlib)
  GET  /auth/callback  -> verify id_token, check ALLOWED_EMAILS, upsert users, set session
  POST /auth/logout    -> clear the session cookie

Middleware: every path except /auth/*, /static/* and /healthz needs a session;
/api/* answers 401 JSON, anything else redirects to /auth/login.
AUTH=off signs every request in as the first ALLOWED_EMAILS address (docker dev and tests), so the
bypass user is always one real sign-in would admit; scripts/check_env.py refuses to boot with it
when ENV=production or when ALLOWED_EMAILS is empty.
Config is read from os.environ per request, so tests can flip it.
"""
import html, json, os, time, uuid
from functools import lru_cache

from authlib.integrations.starlette_client import OAuth, OAuthError
from authlib.jose.errors import JoseError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.datastructures import MutableHeaders

COOKIE = "cf_session"
MAX_AGE = 30 * 24 * 3600  # 30 days
GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"


def auth_off() -> bool: return os.environ.get("AUTH", "").strip().lower() == "off"
def production() -> bool: return os.environ.get("ENV", "").strip().lower() == "production"
def allowed_emails() -> set:
    return {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}


# ---------------------------------------------------------------- session cookie (stateless, itsdangerous)
def serializer():
    secret = os.environ.get("SESSION_SECRET", "")
    return URLSafeTimedSerializer(secret, salt="cf-session") if secret else None

def _load_session(raw) -> dict:
    s = serializer()
    if not (s and raw): return {}
    try: data = s.loads(raw, max_age=MAX_AGE)  # SignatureExpired is a BadSignature
    except BadSignature: return {}
    return data if isinstance(data, dict) else {}

def _cookie_header(session: dict, secure: bool) -> str:
    r = Response()
    if session: r.set_cookie(COOKIE, serializer().dumps(session), max_age=MAX_AGE, httponly=True, secure=secure, samesite="lax")
    else: r.delete_cookie(COOKIE, httponly=True, secure=secure, samesite="lax")
    return r.headers["set-cookie"]

def _public(path: str) -> bool:
    if path == "/healthz" or path.startswith("/auth/"): return True
    return path.startswith("/static/") and path != "/static/index.html"  # the UI shell is only served behind auth

def _identity(session: dict):
    if auth_off():
        first = next((e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()), "")
        return {"email": first, "name": ""} if first else None
    u = session.get("user")
    if isinstance(u, dict) and str(u.get("email", "")).lower() in allowed_emails():  # re-checked every request
        return {"email": u["email"].lower(), "name": u.get("name", "")}
    return None


class AuthMiddleware:
    """Loads the session into scope['session'] (authlib needs it), gates access, re-signs the cookie on change."""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        request = Request(scope)
        session = _load_session(request.cookies.get(COOKIE))
        before = json.dumps(session, sort_keys=True)
        scope["session"] = session
        request.state.user = user = _identity(session)
        if user is None and not _public(scope["path"]):
            resp = (JSONResponse({"detail": "Not authenticated"}, status_code=401) if scope["path"].startswith("/api/")
                    else RedirectResponse("/auth/login", status_code=302))
            return await resp(scope, receive, send)
        secure = production() or request.url.hostname not in ("localhost", "127.0.0.1")

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and serializer() and json.dumps(session, sort_keys=True) != before:
                headers = MutableHeaders(scope=message)
                if not any(v.startswith(COOKIE + "=") for v in headers.getlist("set-cookie")):
                    headers.append("set-cookie", _cookie_header(session, secure))
            await send(message)
        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------- users
def upsert_user(db, email: str, name: str = "") -> dict:
    with db() as d:
        return d.execute(
            "INSERT INTO users(id,email,name,created) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE "
            "SET name=CASE WHEN EXCLUDED.name<>'' THEN EXCLUDED.name ELSE users.name END RETURNING id,email,name",
            (uuid.uuid4().hex, email, name or "", time.time())).fetchone()

def current_user(request: Request) -> dict:
    """FastAPI dependency: the signed-in user's `users` row. Not a data filter yet (single tenant)."""
    user = getattr(request.state, "user", None)
    if not user: raise HTTPException(401, "Not authenticated")
    if "id" not in user:
        user = request.state.user = upsert_user(request.app.state.db, user["email"], user.get("name", ""))
    return user


# ---------------------------------------------------------------- Google OAuth
@lru_cache(maxsize=2)
def _google(client_id: str, client_secret: str):
    return OAuth().register("google", client_id=client_id, client_secret=client_secret,
                            server_metadata_url=GOOGLE_METADATA, client_kwargs={"scope": "openid email profile"})

def google():
    cid, secret = os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")
    return _google(cid, secret) if cid and secret else None

def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<meta name=color-scheme content='light dark'><title>{title} · CognitioFlow</title>"
        "<body style='font:17px/1.5 Charter,Georgia,serif;max-width:32rem;margin:15vh auto;padding:0 1rem'>"
        f"<h1 style='font-weight:500'>{title}</h1>{body}</body>", status_code=status)

router = APIRouter()

@router.get("/auth/login")
async def login(request: Request):
    if auth_off(): return RedirectResponse("/", status_code=302)
    g = google()
    if not g: return _page("Sign-in not configured", "<p>GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set.</p>", 503)
    redirect_uri = str(request.url_for("auth_callback"))
    if production(): redirect_uri = redirect_uri.replace("http://", "https://", 1)  # TLS ends at the Cloud Run proxy
    return await g.authorize_redirect(request, redirect_uri, prompt="select_account")

@router.get("/auth/callback", name="auth_callback")
async def callback(request: Request):
    g = google()
    if auth_off() or not g: return RedirectResponse("/", status_code=302)
    try:
        token = await g.authorize_access_token(request)  # checks state + nonce, verifies id_token against Google's JWKS
    except (OAuthError, JoseError) as e:
        return _page("Sign-in failed", f"<p>{html.escape(str(e) or 'OAuth error')}</p><p><a href='/auth/login'>Try again</a></p>", 400)
    info = token.get("userinfo") or {}
    email = str(info.get("email", "")).strip().lower()
    request.session.clear()
    if not email or info.get("email_verified") is not True:
        return _page("Sign-in failed", "<p>Google did not return a verified email address.</p>", 400)
    if email not in allowed_emails():
        return _page("403 — not allowed", f"<p>{html.escape(email)} is not allowed to use this app.</p>"
                     "<p><a href='/auth/login'>Use another account</a></p>", 403)
    upsert_user(request.app.state.db, email, info.get("name", ""))
    request.session["user"] = {"email": email, "name": info.get("name", "")}
    return RedirectResponse("/", status_code=302)

@router.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    resp = RedirectResponse("/auth/signed-out", status_code=303)
    resp.delete_cookie(COOKIE, httponly=True, secure=production() or request.url.hostname not in ("localhost", "127.0.0.1"), samesite="lax")
    return resp

@router.get("/auth/signed-out")
def signed_out(): return _page("Signed out", "<p><a href='/'>Sign in again</a></p>")


def install(app, db):
    """Wire auth into the app: middleware, /auth/* routes, and the db handle current_user uses."""
    app.state.db = db
    app.add_middleware(AuthMiddleware)
    app.include_router(router)
