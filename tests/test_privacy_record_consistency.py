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
    for needle in ("privacy.anthropic.com", "resources/zero-data-retention", "speech-to-text/docs/data-logging"):
        assert needle in src


def test_principles_table_title_does_not_overclaim():
    assert "## How each GDPR principle is met" not in RECORD
    assert "## GDPR principles: status today" in RECORD


def test_record_header_not_pinned_to_stale_commit():
    assert "f068e36" not in RECORD.split("**In short")[0] and "c10207f" in RECORD.split("**In short")[0]


# --- definition-of-8 (docs) round 5: operator wording, sourced provider claims, honest gaps, roles ---

OPERATOR = "operated by Matej himself, the owner of CognitioFlow; no processing agreement with the providers behind it is on file"
_SCOPE = ("README.md", "docs/privacy-gateway.md", "CLAUDE.md", "llm.py", "gateway.py")


def test_one_operator_sentence_and_no_personal_data_about_the_operator():
    for name in ("README.md", "docs/privacy-gateway.md", "CLAUDE.md", "llm.py"):
        assert OPERATOR in (ROOT / name).read_text(), name
    for name in _SCOPE:
        text = (ROOT / name).read_text().lower()
        for bad in ("family member", "third-party router", "third-party gateway", "matej's own", "operated by a third party", "private individual"):
            assert bad not in text, (name, bad)


def test_every_provider_claim_line_has_source_and_date_or_is_marked():
    """Lines that state a provider's retention, logging, training or certification terms need URL+date or UNVERIFIED/UNKNOWN."""
    claim = re.compile(r"(deleted within|zero.retention|not logged|logging off|trains? on|data privacy framework|certified)", re.I)
    bad = []
    for name in ("docs/privacy-gateway.md", "README.md"):
        for ln, line in enumerate((ROOT / name).read_text().splitlines(), 1):
            if not claim.search(line) or line.startswith("No zero-retention"):
                continue
            sourced = re.search(r"https?://|\b[a-z.-]+\.(com|ai|org)/\S+", line) and re.search(r"20\d\d-\d\d-\d\d", line)
            if not (sourced or re.search(r"UNVERIFIED|UNKNOWN|not checked|not confirmed", line)):
                bad.append(f"{name}:{ln}: {line[:90]}")
    assert not bad, bad


def test_unmet_gdpr_rows_say_not_met_or_open():
    rows = {l.split("|")[1].strip(): l for l in RECORD.splitlines() if l.startswith("| ") and "Art." in l.split("|")[2:3][0] if len(l.split("|")) > 3}
    for key in ("Lawfulness, fairness, transparency", "Processors", "International transfers", "Storage limitation"):
        assert re.search(r"[Nn]ot met|[Oo]pen", rows[key]), key


def test_record_states_roles_gaps_and_open_items():
    for needle in ("## Roles", "Controller for course text", "Art. 2(2)(c)", "second user",
                   "known gap (a)", "(b)", "copyright", "single user", "## Open items", "Who must act"):
        assert needle.lower() in RECORD.lower(), needle
    gaps = RECORD[RECORD.index("## Known gaps"):RECORD.index("## Where data goes today")]
    assert "router's own Google Cloud project" in RECORD and "(a)" in gaps and "(d)" in gaps
    assert "only on the OpenRouter lane" in gaps and "unexamined" in gaps


def test_in_short_is_five_lines_or_fewer_and_operator_section_exists():
    block = RECORD[RECORD.index("**In short"):RECORD.index("### Who operates Kernal")]
    lines = [l for l in block.splitlines() if l.strip() and not l.startswith("**In short")]
    assert 1 <= len(lines) <= 5, len(lines)


def test_open_items_each_name_who_must_act():
    sec = RECORD[RECORD.index("## Open items"):RECORD.index("## Gateway lane configuration")]
    rows = [l for l in sec.splitlines() if re.match(r"\| \d+ \|", l)]
    assert len(rows) >= 7 and all(r.rstrip().endswith("|") and r.count("|") == 4 for r in rows), rows


# --- definition-of-8 (docs) round 6: one coherent legal position; Vertex terms as the saved source says ---

def _row(prefix):
    return next(l for l in RECORD.splitlines() if l.startswith(prefix))


def test_household_exemption_not_relied_on_and_rows_do_not_contradict_it():
    row = _row("| Household exemption")
    assert "Not relied on" in row and "C-101/01" in row and "C-212/13" in row and "UNVERIFIED" in row
    assert "Relied on for single-user" not in RECORD
    # the record is kept under Art. 30 only because it treats the GDPR as applying
    assert "treats the GDPR as applying" in RECORD.split("**State of this record")[0]


def test_art6_row_separates_his_consent_from_third_persons_and_states_a_balancing():
    row = _row("| Lawfulness")
    assert "His consent covers only his own data" in row and "Art. 6(1)(f)" in row
    for needle in ("Interest:", "Necessity:", "Impact and expectations:", "Outcome:"):
        assert needle.replace(":", "") in row, needle
    assert "public and incidental" not in row and re.search(r"[Nn]ot met", row)


def test_vertex_terms_quoted_as_the_saved_source_says_and_openai_30_days_not_misapplied():
    row = _row("| Storage limitation")
    for quote in ('"Google may log prompts to detect potential abuse', '"Request-response logging: This feature is disabled by default"',
                  '"deleted no later than 24 hours after it\'s written"', "OpenAI flagship models", "is not applied to `gemini-2.5-flash`"):
        assert quote in row, quote
    assert "docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention" in row


def test_gateway_does_not_call_redaction_pseudonymisation():
    doc = gateway.__doc__
    assert "pseudonymisation, Art. 4(5))" not in doc and "not pseudonymisation" in doc
