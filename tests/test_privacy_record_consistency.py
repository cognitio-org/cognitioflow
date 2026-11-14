"""The privacy record, CLAUDE.md and gateway.py must tell the same story (RUG pitch, wave 3).

A sceptical reader compares the code's log lines and comments with docs/privacy-gateway.md. These guard
the places that drifted: the fallback provider's name, the 'no-log' claim, CLAUDE.md calling an
unverified finding a fact, the browser-dictation route, the CF_GATEWAY=off state (#234, live 2026-11-14),
the spend ceiling, and unsourced retention terms.
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
    assert "unverified: `ai_calls` not yet read" in md
    assert not (ROOT / "docs" / "pending-protected" / "claude-md-gateway-wording.patch").exists()
    assert "claude-md-gateway-wording" not in (ROOT / "docs" / "pending-protected" / "README.md").read_text()


def test_record_table_has_browser_dictation_row():
    table = RECORD[RECORD.index("## Where data goes today"):RECORD.index("### The OpenRouter lane")]
    rows = [l for l in table.splitlines() if l.startswith("|") and "dictation" in l.lower()]
    assert any("browser" in r.lower() and "Google" in r for r in rows), rows


def test_gateway_off_is_recorded_as_live_not_pending():
    """#234 put CF_GATEWAY=off live on 2026-11-14; no doc may still call it pending or the lane still on."""
    pending = (ROOT / "docs" / "pending-protected" / "README.md").read_text()
    assert "cf-gateway-off" not in pending
    assert not (ROOT / "docs" / "pending-protected" / "cf-gateway-off.patch").exists()
    for name in ("docs/privacy-gateway.md", "README.md", "CLAUDE.md", "gateway.py"):
        text = (ROOT / name).read_text()
        assert "cf-gateway-off.patch" not in text.replace("~~Apply `cf-gateway-off.patch`.~~", ""), name
        assert "still **on**" not in text and "Tried first on the gateway lane" not in text, name
    assert "| `CF_GATEWAY` | `off` disables the lane | **`off`**" in RECORD
    landing = (ROOT / "static" / "landing.html").read_text()
    assert "through OpenRouter" not in landing and "free-tier lane" not in landing


def test_spend_ceiling_not_presented_as_a_working_safeguard():
    art25 = next(l for l in RECORD.splitlines() if l.startswith("| Data protection by design"))
    assert "only works on a LiteLLM gateway" in art25 and "off in production" in art25
    doc = gateway.__doc__
    assert "only works on a LiteLLM gateway" in doc and "without a deploy" not in doc


def test_retention_claims_are_sourced_and_dated():
    row = next(l for l in RECORD.splitlines() if l.startswith("| Storage limitation"))
    assert "checked 2026-11-14" in row and "UNVERIFIED" in row and "UNKNOWN" in row
    src = RECORD[RECORD.index("**Retention sources**"):]
    for needle in ("privacy.anthropic.com", "vertex-ai-zero-data-retention", "speech-to-text/docs/data-logging"):
        assert needle in src


def test_principles_table_title_does_not_overclaim():
    assert "## How each GDPR principle is met" not in RECORD
    assert "## GDPR principles: status today" in RECORD


def test_record_header_not_pinned_to_stale_commit():
    assert "f068e36" not in RECORD.split("**In short")[0]
