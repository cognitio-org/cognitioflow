"""The old service worker on this domain is retired, not left serving a stale app (2026-09-30)."""
import auth


def test_sw_js_is_public_and_retires_itself(client):
    assert auth._public("/sw.js")
    r = client.get("/sw.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert "no-store" in r.headers["cache-control"]
    assert "registration.unregister()" in r.text and "caches.delete" in r.text
