"""CognitioFlow never runs on the paid Anthropic API in production (Matej, 2026-09-30). The deploy does not mount
ANTHROPIC_API_KEY, production refuses to start on any provider but the gateway or OpenRouter, and the features that
used to look for that key now ask the active provider for its own."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import check_env  # noqa: E402

PROD = {"ENV": "production", "DATABASE_URL": "x", "SESSION_SECRET": "s" * 40, "GOOGLE_CLIENT_ID": "g",
        "GOOGLE_CLIENT_SECRET": "g", "ALLOWED_EMAILS": "matej@mgms.eu", "LITELLM_API_KEY": "k"}


@pytest.mark.parametrize("provider", ["", "anthropic", "ANTHROPIC"])
def test_production_refuses_to_start_on_the_anthropic_api(provider):
    with pytest.raises(RuntimeError, match="never the Anthropic API"):
        check_env.enforce({**PROD, "LLM_PROVIDER": provider, "ANTHROPIC_API_KEY": "sk-ant-real"})


@pytest.mark.parametrize("provider,key", [("gateway", "LITELLM_API_KEY"), ("openrouter", "OPENROUTER_KEY")])
def test_production_starts_on_the_gateway_or_openrouter_without_an_anthropic_key(provider, key):
    env = {k: v for k, v in PROD.items() if k != "LITELLM_API_KEY"} | {"LLM_PROVIDER": provider, key: "k"}
    check_env.enforce(env)


def test_the_deploy_no_longer_mounts_the_anthropic_key():
    wf = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows", "deploy.yml")).read()
    deploy = wf[wf.index("gcloud run deploy"):wf.index("Smoke test /health")]
    assert "ANTHROPIC_API_KEY" not in deploy and "LLM_PROVIDER=gateway" in deploy and "LITELLM_API_KEY=" in deploy


def test_config_reports_the_active_providers_key_not_the_anthropic_one(client, monkeypatch):
    import run
    monkeypatch.setattr(run.llm, "has_key", lambda: False)
    assert client.get("/api/config").json()["has_key"] is False
    monkeypatch.setattr(run.llm, "has_key", lambda: True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/config").json()["has_key"] is True     # the tutor's Send works on the gateway key alone


def test_nothing_in_the_app_looks_for_the_anthropic_key_any_more():
    root = os.path.dirname(os.path.dirname(__file__))
    for name in ("run.py", "gateway.py"):
        assert "ANTHROPIC_API_KEY" not in open(os.path.join(root, name)).read(), name
