"""Write-scoped keys (approved 2026-11-09, for the lecture pipeline): a cfw_ key may POST a finished lecture
note to exactly ONE bound course's /files and /cards/generate, keeps read access, and nothing else. Only the
owner's signed-in session makes one; it carries a per-key course binding and a hard expiry. Read keys unaffected.

These assert the AuthMiddleware GATE (allow/refuse), not the upload/card handlers downstream, so they don't
depend on storage or an LLM being wired in CI: the positive upload case asserts only that auth let it through."""
import time

import auth


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _write_key(client, cid, ttl_days=7):
    r = client.post("/api/tokens", json={"scope": "write", "course_id": cid, "ttl_days": ttl_days})
    assert r.status_code == 200, r.text
    return r.json()


def test_owner_mints_a_write_key_bound_to_one_course(client):
    cid = client.post("/api/courses", json={"name": "Write Law"}).json()["id"]
    k = _write_key(client, cid)
    assert k["token"].startswith("cfw_") and len(k["token"]) > 40
    assert k["scope"] == "write" and k["course_id"] == cid and k["expires"] > time.time()
    assert k["writes"] == [f"/api/courses/{cid}/files", f"/api/courses/{cid}/cards/generate"]


def test_write_key_passes_the_gate_for_its_own_course_files(client):
    cid = client.post("/api/courses", json={"name": "Own Course"}).json()["id"]
    tok = _write_key(client, cid)["token"]
    r = client.post(f"/api/courses/{cid}/files",
                    files={"file": ("wk1_lecture.md", b"# PIL notes\n\nSources of law.\n", "text/markdown")},
                    data={"week": "1"}, headers=_h(tok))
    assert r.status_code not in (401, 403), r.text   # auth let it reach the handler (handler success is tested elsewhere)


def test_write_key_is_refused_for_another_course(client):
    a = client.post("/api/courses", json={"name": "Bound"}).json()["id"]
    b = client.post("/api/courses", json={"name": "Other"}).json()["id"]
    tok = _write_key(client, a)["token"]
    r = client.post(f"/api/courses/{b}/files",
                    files={"file": ("x.md", b"# x", "text/markdown")}, data={"week": "1"}, headers=_h(tok))
    assert r.status_code == 403 and "bound course" in r.json()["detail"]


def test_a_read_key_cannot_write(client):
    cid = client.post("/api/courses", json={"name": "ReadOnly"}).json()["id"]
    rtok = client.post("/api/tokens").json()["token"]
    assert rtok.startswith("cfr_")
    r = client.post(f"/api/courses/{cid}/files",
                    files={"file": ("x.md", b"# x", "text/markdown")}, data={"week": "1"}, headers=_h(rtok))
    assert r.status_code == 403 and "reads Today" in r.json()["detail"]


def test_write_key_cannot_touch_other_routes_but_keeps_read_access(client):
    cid = client.post("/api/courses", json={"name": "Scope"}).json()["id"]
    tok = _write_key(client, cid)["token"]
    assert client.get("/api/courses", headers=_h(tok)).status_code == 403          # not a write route, not a read route
    assert client.post(f"/api/courses/{cid}/chat", headers=_h(tok)).status_code == 403
    assert client.get("/api/today", headers=_h(tok)).status_code == 200            # read access is additive


def test_a_write_key_can_never_manage_keys(client):
    cid = client.post("/api/courses", json={"name": "NoAdmin"}).json()["id"]
    tok = _write_key(client, cid)["token"]
    assert client.post("/api/tokens", json={"scope": "write", "course_id": cid}, headers=_h(tok)).status_code == 403
    assert client.get("/api/tokens", headers=_h(tok)).status_code == 403


def test_an_expired_write_key_is_401(client, pg):
    cid = client.post("/api/courses", json={"name": "Expiry"}).json()["id"]
    k = _write_key(client, cid)
    assert client.get("/api/today", headers=_h(k["token"])).status_code == 200     # live now
    pg.execute("UPDATE api_tokens SET expires=%s WHERE id=%s", (time.time() - 10, k["id"]))
    pg.commit()
    assert client.get("/api/today", headers=_h(k["token"])).status_code == 401     # past expiry -> refused like revoked


def test_minting_a_write_key_needs_a_real_course(client):
    assert client.post("/api/tokens", json={"scope": "write"}).status_code == 400            # no course_id
    assert client.post("/api/tokens", json={"scope": "write", "course_id": "nope"}).status_code == 404


def test_only_the_owner_session_mints_write_keys(client, monkeypatch, ack_privacy):
    cid = client.post("/api/courses", json={"name": "OwnerOnly"}).json()["id"]
    monkeypatch.setenv("OWNER_EMAIL", "someone.else@example.com")
    ack_privacy(client)   # past the privacy gate (428), so the owner check itself is what refuses
    assert client.post("/api/tokens", json={"scope": "write", "course_id": cid}).status_code == 403
