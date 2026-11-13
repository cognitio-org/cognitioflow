"""The privacy record, CLAUDE.md and gateway.py must tell the same story (RUG pitch, wave 3).

A sceptical reader compares the code's log lines and comments with docs/privacy-gateway.md. These guard
the places that drifted: the fallback provider's name, the 'no-log' claim, CLAUDE.md calling an
unverified finding a fact, the browser-dictation route, and the two gcloud fallback commands.
"""
import logging
import pathlib
import re

import gateway

ROOT = pathlib.Path(__file__).resolve().parent.parent
RECORD = (ROOT / "docs" / "privacy-gateway.md").read_text()


def _on(monkeypatch):
    monkeypatch.setattr(gateway, "_tripped", False)
    for k in ("CF_GATEWAY", "CF_GATEWAY_TASKS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    monkeypatch.setenv("CF_GATEWAY_SPEND_CEILING", "113")


def test_failure_log_names_the_cheap_tier_not_anthropic(monkeypatch, caplog):
    import anthropic
    _on(monkeypatch)

    def boom(**kw):
        raise RuntimeError("down")
    monkeypatch.setattr(anthropic, "Anthropic", boom)
    with caplog.at_level(logging.WARNING, logger=gateway.log.name):
        assert gateway.call("cards", max_tokens=10, messages=[{"role": "user", "content": "x"}]) is None
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "cheap tier" in text and "Anthropic" not in text


def test_ceiling_log_names_the_cheap_tier_not_anthropic(monkeypatch, caplog):
    import anthropic
    _on(monkeypatch)

    class Raw:
        headers = {"x-litellm-key-spend": "200"}

        def parse(self):
            class M:
                content = [type("B", (), {"type": "text", "text": "[]"})()]
                usage = type("U", (), {})()
                stop_reason = "end_turn"
            return M()

    class Fake:
        class messages:
            class with_raw_response:
                @staticmethod
                def create(**kw):
                    return Raw()
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: Fake())
    with caplog.at_level(logging.WARNING, logger=gateway.log.name):
        assert gateway.call("cards", max_tokens=10, messages=[{"role": "user", "content": "x"}]) is not None
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ceiling" in text and "cheap tier" in text and "Anthropic" not in text


def test_gateway_source_has_no_anthropic_fallback_claim():
    src = (ROOT / "gateway.py").read_text()
    assert not re.search(r"(on|to|back to) Anthropic\b(?! directly)", src), "fallback is the configured cheap tier"


def test_no_log_claim_is_qualified():
    doc = gateway.__doc__
    line = next(l for l in doc.splitlines() if "Art. 5(1)(e)" in l)
    block = doc[doc.index(line):doc.index("Integrity")]
    assert "OpenRouter" in block and "not" in block, "no-log is only honoured by a LiteLLM gateway"


def test_claude_md_does_not_state_unverified_finding_as_fact():
    md = (ROOT / "CLAUDE.md").read_text()
    assert "a dead OpenRouter free model" not in md
    assert "probably dead (unverified" in md
    assert not (ROOT / "docs" / "pending-protected" / "claude-md-gateway-wording.patch").exists()
    assert "claude-md-gateway-wording" not in (ROOT / "docs" / "pending-protected" / "README.md").read_text()


def test_record_table_has_browser_dictation_row():
    table = RECORD[RECORD.index("## Where data goes today"):RECORD.index("### The OpenRouter lane")]
    rows = [l for l in table.splitlines() if l.startswith("|") and "dictation" in l.lower()]
    assert any("browser" in r.lower() and "Google" in r for r in rows), rows


def test_gcloud_fallback_commands_match():
    pending = (ROOT / "docs" / "pending-protected" / "README.md").read_text()
    pat = r"`(gcloud run services update[^`]*)`"
    assert re.findall(pat, RECORD) == re.findall(pat, pending) != []


def test_record_header_not_pinned_to_stale_commit():
    assert "f068e36" not in RECORD.split("**In short")[0]
