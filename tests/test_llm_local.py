"""Phase 18 — the self-hosted (local) tier of the model seam. No test reaches a real endpoint."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm as _llm  # noqa: E402


@pytest.fixture
def local_on(monkeypatch):
    """Turn the local tier on without touching the real environment or reloading the module."""
    monkeypatch.setattr(_llm, "LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(_llm, "LOCAL_MODEL", "qwen2.5:7b-instruct")
    monkeypatch.setattr(_llm, "LOCAL_TASKS", ("cards",))
    return _llm


# ---- default OFF ---------------------------------------------------------------------------

def test_local_is_off_by_default():
    """With CF_LOCAL_BASE_URL unset, nothing routes local — the cheap tier is byte-for-byte today's."""
    assert _llm.local_enabled() is False
    assert _llm.local_allows("cards") is False
    assert _llm.local_call("cards", messages=[{"role": "user", "content": "x"}]) is None


def test_local_allows_only_listed_tasks(local_on):
    assert local_on.local_enabled() is True
    assert local_on.local_allows("cards") is True
    assert local_on.local_allows("drill") is False   # main tier never goes local
    assert local_on.local_allows("concepts") is False  # not on the list until it clears the bar
    assert local_on.local_allows("") is False


# ---- Anthropic → OpenAI translation --------------------------------------------------------

def test_system_becomes_a_system_message_and_content_flattens():
    msgs = _llm._to_openai_messages(
        "GROUND ONLY IN THE TEXT",
        [{"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}])
    assert msgs[0] == {"role": "system", "content": "GROUND ONLY IN THE TEXT"}
    assert msgs[1] == {"role": "user", "content": "a\n\nb"}


def test_no_system_message_when_system_is_absent():
    msgs = _llm._to_openai_messages(None, [{"role": "user", "content": "hi"}])
    assert msgs == [{"role": "user", "content": "hi"}]


# ---- the bridge: request body and response parsing -----------------------------------------

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
        captured["timeout"] = timeout
        return _FakeResp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_local_create_builds_openai_body_and_returns_anthropic_shape(local_on, monkeypatch):
    captured = {}
    _patch_urlopen(monkeypatch, {
        "model": "qwen2.5:7b-instruct",
        "choices": [{"message": {"content": "[{\"front\":\"Q\",\"back\":\"A\"}]"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 80},
    }, captured)

    m = local_on.local_create(system="S", messages=[{"role": "user", "content": "material"}], max_tokens=3000)

    # request: OpenAI chat-completions, non-streaming, system prepended
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["model"] == "qwen2.5:7b-instruct"
    assert captured["body"]["stream"] is False
    assert captured["body"]["max_tokens"] == 3000
    assert captured["body"]["messages"][0]["role"] == "system"
    # response: the Anthropic shape run.py reads
    assert m.content[0].type == "text" and "front" in m.content[0].text
    assert m.model == "qwen2.5:7b-instruct"
    assert m.stop_reason == "end_turn"
    # usage: provider=local, cost 0 (own hardware) — the honest Phase-9 cost readout
    u = local_on.usage(m, "cards")
    assert u["provider"] == "local" and u["cost"] == 0
    assert u["in"] == 1200 and u["out"] == 80


def test_finish_length_maps_to_max_tokens(local_on, monkeypatch):
    _patch_urlopen(monkeypatch, {
        "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }, {})
    m = local_on.local_create(messages=[{"role": "user", "content": "x"}], max_tokens=10)
    assert m.stop_reason == "max_tokens"   # so _mark_if_cut / the Continue button still work


# ---- fall-back contract (mirrors gateway.call) ---------------------------------------------

def test_local_call_falls_back_to_none_on_transport_error(local_on, monkeypatch):
    import urllib.request

    def boom(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert local_on.local_call("cards", messages=[{"role": "user", "content": "x"}]) is None


def test_local_call_falls_back_when_the_answer_is_empty(local_on, monkeypatch):
    _patch_urlopen(monkeypatch, {
        "choices": [{"message": {"content": "   "}, "finish_reason": "stop"}], "usage": {},
    }, {})
    assert local_on.local_call("cards", messages=[{"role": "user", "content": "x"}]) is None


def test_describe_reports_the_local_tier(local_on):
    d = local_on.describe()
    assert d["local"]["enabled"] is True
    assert d["local"]["model"] == "qwen2.5:7b-instruct"
    assert d["local"]["tasks"] == ["cards"]
