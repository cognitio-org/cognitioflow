"""One canonical host, so sign-in only ever sends Google one redirect_uri.

2026-09-19: cognitioflow.ai and www.cognitioflow.ai were mapped to the same Cloud Run service as
app.cognitioflow.ai. auth.py builds the OAuth redirect_uri from the REQUEST host, so a visitor
arriving at the apex would be sent to Google with a redirect_uri the OAuth client does not list,
and Google answers redirect_uri_mismatch. The middleware sends every other host to the canonical
one before auth runs, so the apex works without touching the OAuth client at all.
"""
import os

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH", "off")
    monkeypatch.setenv("CANONICAL_HOST", "app.cognitioflow.ai")
    import run
    monkeypatch.setattr(run, "CANONICAL_HOST", "app.cognitioflow.ai")
    return TestClient(run.app, follow_redirects=False)


@pytest.fixture
def unset(monkeypatch):
    import run
    monkeypatch.setattr(run, "CANONICAL_HOST", "")
    return TestClient(run.app, follow_redirects=False)


@pytest.mark.parametrize("host", ["cognitioflow.ai", "www.cognitioflow.ai"])
def test_other_hosts_are_sent_to_the_canonical_one(client, host):
    r = client.get("/health", headers={"host": host})
    assert r.status_code == 308
    assert r.headers["location"] == "https://app.cognitioflow.ai/health"


def test_the_canonical_host_is_served_not_redirected(client):
    r = client.get("/health", headers={"host": "app.cognitioflow.ai"})
    assert r.status_code == 200


def test_the_path_and_query_survive_the_redirect(client):
    r = client.get("/auth/login?next=/print", headers={"host": "cognitioflow.ai"})
    assert r.status_code == 308
    assert r.headers["location"] == "https://app.cognitioflow.ai/auth/login?next=/print"


def test_a_post_keeps_its_method(client):
    # 308, not 302: a 302 would turn a POST into a GET and lose the body
    r = client.post("/api/courses", json={"name": "x"}, headers={"host": "cognitioflow.ai"})
    assert r.status_code == 308


def test_the_cloud_run_url_and_localhost_are_left_alone(client):
    # health checks and local dev must not be bounced at a public hostname
    for host in ("cognitioflow-sarfwmfd3q-ez.a.run.app", "localhost", "testserver"):
        assert client.get("/health", headers={"host": host}).status_code == 200


def test_it_is_off_unless_a_canonical_host_is_configured(unset):
    # the default, and what every test and local hostname sees
    assert unset.get("/health", headers={"host": "cognitioflow.example"}).status_code == 200


def test_the_deployed_service_is_told_its_canonical_host():
    # The middleware is off unless CANONICAL_HOST is set, and the deploy step's --set-env-vars
    # replaces every variable on each release - so a value set by hand in the console is wiped by
    # the next merge. From 2026-09-19 to 2026-09-23 it was never set at all, and sign-in at
    # cognitioflow.ai failed with redirect_uri_mismatch. The deploy file is the only place it can live.
    with open(os.path.join(ROOT, ".github", "workflows", "deploy.yml")) as f:
        assert "CANONICAL_HOST=cognitioflow.ai" in f.read()
