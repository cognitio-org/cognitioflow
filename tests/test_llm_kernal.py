"""Phase 19 — the Kernal cloud tier of the model seam (LLM_PROVIDER=kernal). No test reaches a real
endpoint: urllib is patched. The anthropic/openrouter/gateway paths are unchanged and default-off."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm as _llm  # noqa: E402


@pytest.fixture
def kernal(monkeypatch):
    """Switch the seam to the kernal provider without touching the real environment."""
    monkeypatch.setattr(_llm, "PROVIDER", "kernal")
    monkeypatch.setenv("KERNAL_API_KEY", "kr-test")
    return _llm


# ---- defaults, routing and the allow-list --------------------------------------------------

def test_kernal_is_not_the_default():
    """With LLM_PROVIDER unset the seam is anthropic — the kernal path is never reached."""
    assert _llm.PROVIDER == "anthropic"


def test_kernal_defaults(kernal):
    assert kernal.default_model("main") == "claude-sonnet-5"      # Matej's router serves Sonnet
    assert kernal.default_model("cheap") == "gemini-2.5-flash"
    assert kernal.key_name() == "KERNAL_API_KEY" and kernal.has_key() is True


def test_kernal_resolve_passes_names_through(kernal):
    # kernal takes its own ids, not OpenRouter's dotted spelling
    assert kernal.resolve("claude-sonnet-5") == "claude-sonnet-5"
    assert kernal.resolve("gemini-2.5-flash") == "gemini-2.5-flash"
    with pytest.raises(kernal.ConfigError):
        kernal.resolve("openrouter/auto")   # a router id is still refused everywhere


def test_kernal_catalogue_offers_both_tiers_never_a_router_or_fable(kernal, monkeypatch):
    monkeypatch.setenv("CF_PICKER_MODELS", "gemini-2.5-flash,claude-opus-5,openrouter/auto,gpt-5-nano")
    cat = kernal.catalogue()
    assert "claude-sonnet-5" in cat and "gemini-2.5-flash" in cat and "gpt-5-nano" in cat
    assert "claude-opus-5" not in cat and "openrouter/auto" not in cat   # EXPENSIVE + router refused


def test_describe_is_unaffected_by_the_kernal_provider(kernal):
    d = kernal.describe()
    assert d["provider"] == "kernal" and d["has_key"] is True
    assert d["local"]["enabled"] is False   # the self-hosted tier is independent and still off


# ---- the OpenAI bridge: non-streaming create -----------------------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, payload, captured):
    import urllib.request

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_create_builds_openai_body_and_returns_anthropic_shape(kernal, monkeypatch):
    captured = {}
    _patch_urlopen(monkeypatch, {
        "model": "claude-sonnet-5",
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50},
    }, captured)

    c = kernal.client()
    m = c.messages.create(model="claude-sonnet-5", max_tokens=2000, system="SYS",
                          messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}])
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["model"] == "claude-sonnet-5" and captured["body"]["stream"] is False
    assert captured["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert captured["auth"] == "Bearer kr-test"
    assert m.content[0].type == "text" and m.content[0].text == "hello"
    assert m.model == "claude-sonnet-5" and m.stop_reason == "end_turn"

    # usage(): provider filled to kernal, and cost computed from PRICES for a priced model (Sonnet)
    u = kernal.usage(m, "drill")
    assert u["provider"] == "kernal" and u["in"] == 1000 and u["out"] == 50
    assert u["cost"] is not None and u["cost"] > 0


def test_cost_is_unknown_for_an_unpriced_model_not_guessed(kernal, monkeypatch):
    _patch_urlopen(monkeypatch, {
        "choices": [{"message": {"content": "x"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }, {})
    m = kernal.client().messages.create(model="gemini-2.5-flash", max_tokens=10,
                                        messages=[{"role": "user", "content": "x"}])
    assert m.stop_reason == "max_tokens"   # finish_reason length → max_tokens, so Continue still works
    u = kernal.usage(m, "cards")
    assert u["provider"] == "kernal" and u["cost"] is None   # no price table entry → honest unknown


# ---- the OpenAI bridge: streaming (the one tutor-chat call) --------------------------------

def test_stream_reads_sse_deltas_and_builds_the_final_message(kernal, monkeypatch):
    import urllib.request

    lines = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":2}}\n',
        b'data: [DONE]\n',
    ]

    class _SSEResp:
        def __init__(self, rows):
            self._rows = iter(rows)
        def __iter__(self):
            return self._rows
        def close(self):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _SSEResp(lines))

    with kernal.client().messages.stream(model="claude-sonnet-5", max_tokens=100,
                                         messages=[{"role": "user", "content": "hi"}]) as s:
        assert "".join(s.text_stream) == "Hello"
        final = s.get_final_message()
    assert final.content[0].text == "Hello" and final.stop_reason == "end_turn"
    u = kernal.usage(final, "drill")
    assert u["provider"] == "kernal" and u["in"] == 7 and u["out"] == 2


def test_hedged_stream_works_over_the_kernal_shim(kernal, monkeypatch):
    """run.py's one streaming call goes through llm.hedged_stream(make_client, …); the kernal shim must
    satisfy that contract (text_stream + get_final_message, usable as a context manager)."""
    import urllib.request

    lines = [b'data: {"choices":[{"delta":{"content":"ok"}}]}\n', b'data: [DONE]\n']

    class _SSEResp:
        def __iter__(self):
            return iter(lines)
        def close(self):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _SSEResp())
    with kernal.hedged_stream(kernal.client, hedge_s=0, model="claude-sonnet-5", max_tokens=10,
                              messages=[{"role": "user", "content": "hi"}]) as s:
        assert "".join(s.text_stream) == "ok"
