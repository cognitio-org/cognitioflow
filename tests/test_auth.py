"""Phase 4: Google sign-in, session cookie, AUTH=off bypass, boot refusal.

Google is never contacted: server metadata (with an inline JWKS) and the code-for-token exchange
are mocked, but the id_token is a real RS256 JWT, so authlib's signature/iss/aud/nonce checks run.
"""
import os
import subprocess
import sys
import time
import unittest.mock as mock
from urllib.parse import parse_qs, urlparse

import psycopg
import pytest
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from authlib.jose import JsonWebKey, jwt
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT_ID = "test-client.apps.googleusercontent.com"
ISSUER = "https://accounts.google.com"
KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test"})
OTHER_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test"})


@pytest.fixture
def auth_on(monkeypatch):
    import auth
    monkeypatch.delenv("AUTH", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.setenv("ALLOWED_EMAILS", "matej@mgms.eu, second@example.com")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    auth._google.cache_clear()
    yield auth
    auth._google.cache_clear()


@pytest.fixture
def web(auth_on):
    from run import app, init
    init()
    return TestClient(app, base_url="http://localhost")


def _cookie_for(auth, email, name=""):
    return auth.serializer().dumps({"user": {"email": email, "name": name}})


async def _metadata(self):
    return {"issuer": ISSUER, "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks": {"keys": [KEY.as_dict(is_private=False)]}}


def _google_flow(web, email, *, key=KEY, verified=True, state_override=None):
    """Drive /auth/login -> /auth/callback with Google mocked. Returns the callback response."""
    with mock.patch.object(StarletteOAuth2App, "load_server_metadata", _metadata):
        r = web.get("/auth/login", follow_redirects=False)
        assert r.status_code == 302, r.text
        q = parse_qs(urlparse(r.headers["location"]).query)
        assert r.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert q["client_id"] == [CLIENT_ID] and q["redirect_uri"] == ["http://localhost/auth/callback"]
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "1234", "email": email, "email_verified": verified,
                  "name": "Test User", "iat": now, "exp": now + 600, "nonce": q["nonce"][0]}
        id_token = jwt.encode({"alg": "RS256", "kid": "test"}, claims, key).decode()

        async def fake_fetch(self, **kw):
            assert kw.get("code") == "authcode"
            return {"access_token": "at", "token_type": "Bearer", "expires_in": 3600, "id_token": id_token}

        with mock.patch.object(StarletteOAuth2App, "fetch_access_token", fake_fetch):
            return web.get("/auth/callback", params={"code": "authcode", "state": state_override or q["state"][0]},
                           follow_redirects=False)


# ---------------------------------------------------------------- gate

def test_healthz_needs_no_auth(web):
    r = web.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_api_without_cookie_is_401_json(web):
    r = web.get("/api/courses")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}


def test_ui_redirects_to_login(web):
    r = web.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/auth/login"
    assert web.get("/static/index.html", follow_redirects=False).status_code == 302  # shell only behind auth
    assert web.get("/static/marked.min.js").status_code == 200


def test_bearer_header_is_not_a_credential(web):
    r = web.get("/api/courses", headers={"Authorization": "Bearer " + "a" * 40})
    assert r.status_code == 401


def test_valid_session_cookie_is_200(web, auth_on):
    web.cookies.set("cf_session", _cookie_for(auth_on, "matej@mgms.eu"))
    assert web.get("/api/courses").status_code == 200
    assert web.get("/", follow_redirects=False).status_code == 200


def test_bad_cookies_are_rejected(web, auth_on):
    for value in (_cookie_for(auth_on, "intruder@example.com"),     # signed, but not allow-listed
                  _cookie_for(auth_on, "matej@mgms.eu")[:-2] + "xx"):  # tampered signature
        web.cookies.set("cf_session", value)
        assert web.get("/api/courses").status_code == 401
    with mock.patch("itsdangerous.timed.time.time", return_value=time.time() - 31 * 24 * 3600):
        old = _cookie_for(auth_on, "matej@mgms.eu")  # older than 30 days
    web.cookies.set("cf_session", old)
    assert web.get("/api/courses").status_code == 401


def test_removing_email_from_allow_list_revokes_session(web, auth_on, monkeypatch):
    web.cookies.set("cf_session", _cookie_for(auth_on, "second@example.com"))
    assert web.get("/api/courses").status_code == 200
    monkeypatch.setenv("ALLOWED_EMAILS", "matej@mgms.eu")
    assert web.get("/api/courses").status_code == 401


def test_session_is_stateless_across_restart(auth_on):
    """A cookie depends only on SESSION_SECRET: a separate, freshly built app accepts it."""
    from fastapi import FastAPI
    cookie = _cookie_for(auth_on, "matej@mgms.eu")
    app = FastAPI()
    auth_on.install(app, None)
    app.get("/api/ping")(lambda: {"ok": True})
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("cf_session", cookie)
    assert c.get("/api/ping").status_code == 200


# ---------------------------------------------------------------- Google flow (mocked)

def test_google_sign_in_allow_listed(web, pg):
    r = _google_flow(web, "Matej@mgms.eu")
    assert r.status_code == 302 and r.headers["location"] == "/"
    set_cookie = r.headers["set-cookie"]
    assert "cf_session=" in set_cookie and "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie
    assert "Max-Age=2592000" in set_cookie and "Secure" not in set_cookie  # localhost
    assert web.get("/api/courses").status_code == 200
    assert web.get("/api/config").json()["email"] == "matej@mgms.eu"
    row = pg.execute("SELECT email, name FROM users WHERE email=%s", ("matej@mgms.eu",)).fetchone()
    assert row == ("matej@mgms.eu", "Test User")


def test_google_sign_in_not_allow_listed_is_403(web, pg):
    r = _google_flow(web, "someone@gmail.com")
    assert r.status_code == 403 and "text/html" in r.headers["content-type"]
    assert "not allowed" in r.text
    assert web.get("/api/courses").status_code == 401
    assert pg.execute("SELECT 1 FROM users WHERE email=%s", ("someone@gmail.com",)).fetchone() is None


def test_google_unverified_email_rejected(web):
    assert _google_flow(web, "matej@mgms.eu", verified=False).status_code == 400
    assert web.get("/api/courses").status_code == 401


def test_id_token_with_wrong_signature_rejected(web):
    r = _google_flow(web, "matej@mgms.eu", key=OTHER_KEY)
    assert r.status_code == 400
    assert web.get("/api/courses").status_code == 401


def test_state_mismatch_rejected(web):
    r = _google_flow(web, "matej@mgms.eu", state_override="forged-state")
    assert r.status_code == 400
    assert web.get("/api/courses").status_code == 401


def test_cookie_is_secure_off_localhost(auth_on):
    from run import app
    c = TestClient(app, base_url="http://cognitioflow.example")
    with mock.patch.object(StarletteOAuth2App, "load_server_metadata", _metadata):
        r = c.get("/auth/login", follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]


def test_login_without_oauth_client_is_503(web, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    assert web.get("/auth/login", follow_redirects=False).status_code == 503


def test_logout_clears_cookie(web):
    assert _google_flow(web, "matej@mgms.eu").status_code == 302  # cookie set by the server
    assert web.get("/api/courses").status_code == 200
    r = web.post("/auth/logout", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/auth/signed-out"
    assert r.headers["set-cookie"].startswith('cf_session=""') and "Max-Age=0" in r.headers["set-cookie"]
    assert len(r.headers.get_list("set-cookie")) == 1
    assert web.get("/api/courses").status_code == 401
    assert web.get("/auth/signed-out").status_code == 200


# ---------------------------------------------------------------- AUTH=off + current_user

def test_auth_off_signs_in_as_matej(client, pg, monkeypatch):
    monkeypatch.setenv("AUTH", "off")
    monkeypatch.setenv("ALLOWED_EMAILS", "matej@mgms.eu, second@example.com")
    monkeypatch.setenv("MATEJ_EMAIL", "someone-else@example.com")  # ignored: the bypass uses the allow-list
    monkeypatch.delenv("ENV", raising=False)
    assert client.get("/", follow_redirects=False).status_code == 200
    cfg = client.get("/api/config").json()
    assert cfg["email"] == "matej@mgms.eu" and isinstance(cfg["has_key"], bool)
    assert os.environ["ANTHROPIC_API_KEY"] not in client.get("/api/config").text
    cid = client.post("/api/courses", json={"name": "Tort", "accent": "#123456"}).json()["id"]
    uid = pg.execute("SELECT id FROM users WHERE email='matej@mgms.eu'").fetchone()[0]
    assert pg.execute("SELECT user_id FROM courses WHERE id=%s", (cid,)).fetchone()[0] == uid


def test_new_course_gets_signed_in_user(web, auth_on, pg):
    web.cookies.set("cf_session", _cookie_for(auth_on, "second@example.com"))
    cid = web.post("/api/courses", json={"name": "Contract"}).json()["id"]
    row = pg.execute("SELECT u.email FROM courses c JOIN users u ON u.id=c.user_id WHERE c.id=%s", (cid,)).fetchone()
    assert row == ("second@example.com",)


def test_index_never_mentions_the_key_variable():
    with open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8") as f:
        assert "ANTHROPIC_API_KEY" not in f.read()


# ---------------------------------------------------------------- boot checks

def test_check_env_rules(tmp_path):
    from scripts.check_env import enforce, problems
    base = {"DATABASE_URL": "postgresql://x", "ANTHROPIC_API_KEY": "k", "SESSION_SECRET": "s" * 40,
            "GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "sec", "ALLOWED_EMAILS": "a@b.c"}
    assert problems({**base, "ENV": "production"}) == []
    with pytest.raises(RuntimeError, match="AUTH=off"):
        enforce({**base, "ENV": "production", "AUTH": "off"})
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_SECRET"):
        enforce({**base, "ENV": "production", "GOOGLE_CLIENT_SECRET": ""})
    enforce({"DATABASE_URL": "x", "AUTH": "off", "ALLOWED_EMAILS": "m@x"})           # dev bypass boots
    with pytest.raises(RuntimeError, match="ALLOWED_EMAILS"):
        enforce({"DATABASE_URL": "x", "AUTH": "off", "MATEJ_EMAIL": "m@x"})          # bypass needs an allow-list, not MATEJ_EMAIL
    enforce({"DATABASE_URL": "x", "SESSION_SECRET": "short"})                         # dev without OAuth client boots (warns)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        enforce({"DATABASE_URL": "x"})                                                # auth on needs a secret
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check_env.py")], cwd=tmp_path,
                       capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert r.returncode == 1 and "DATABASE_URL is not set" in r.stdout


def test_production_with_auth_off_refuses_to_boot():
    env = {**os.environ, "ENV": "production", "AUTH": "off", "CF_WHISPER_PRELOAD": "0"}
    r = subprocess.run([sys.executable, "-c", "import run"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "AUTH=off is not allowed when ENV=production" in r.stderr


def test_health_needs_no_auth_for_cloud_run(web):
    """Cloud Run's front end answers /healthz itself with a 404 (paths ending in z are reserved), so probes use /health."""
    r = web.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True}
