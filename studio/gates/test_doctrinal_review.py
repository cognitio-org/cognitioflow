"""Self-contained tests for doctrinal_review gate — no pytest required."""

import json
import sys
import os

# Ensure the repo root is on sys.path so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

from studio.gates.doctrinal_review import (
    build_prompt, build_distractor_prompt, review_doctrine, review_distractor,
    parse_verdict, unverified_quotes, DoctrineVerdict,
)

FENCE = "`" * 3  # a markdown code fence, built so this file never contains one literally

SOURCE = ("A contract requires offer, acceptance and consideration.\n"
          "An offer   may be revoked at any time before acceptance.")


def test_ok_true():
    """(a) Stub reviewer returning ok=true → verdict.ok is True."""
    def stub_reviewer(prompt: str) -> str:
        return '{"ok": true, "issues": []}'

    verdict = review_doctrine("source text", "generated text", stub_reviewer)
    assert verdict.ok is True, f"Expected ok=True, got {verdict.ok}"
    assert verdict.issues == [], f"Expected no issues, got {verdict.issues}"
    assert verdict.raw == '{"ok": true, "issues": []}'
    print("  (a) ok=true stub: PASS")


def test_fenced_json():
    """(b) Stub returning markdown-fenced JSON with ok=false → ok False, issue captured."""
    def stub_reviewer(prompt: str) -> str:
        return FENCE + 'json\n{"ok": false, "issues": ["invented a defence"]}\n' + FENCE

    verdict = review_doctrine("source text", "generated text", stub_reviewer)
    assert verdict.ok is False, f"Expected ok=False, got {verdict.ok}"
    assert "invented a defence" in verdict.issues, f"Expected issue captured, got {verdict.issues}"
    print("  (b) fenced JSON stub: PASS")


def test_garbage_fail_closed():
    """(c) Stub returning garbage → ok False, fail-closed with specific message."""
    def stub_reviewer(prompt: str) -> str:
        return 'the model was confused'

    verdict = review_doctrine("source text", "generated text", stub_reviewer)
    assert verdict.ok is False, f"Expected ok=False, got {verdict.ok}"
    assert verdict.issues == ["unparseable reviewer output"], f"Expected fail-closed issues, got {verdict.issues}"
    print("  (c) garbage stub (fail-closed): PASS")


def test_build_prompt_contains_texts():
    """(d) build_prompt output contains both the source and generated text."""
    source = "The rule of perpetuities limits future interests."
    generated = "Future interests are unlimited under common law."
    prompt = build_prompt(source, generated)
    assert source in prompt, "Source text not found in prompt"
    assert generated in prompt, "Generated text not found in prompt"
    print("  (d) build_prompt contains both texts: PASS")


def _says(ok, issues=(), quotes=None):
    body = {"ok": ok, "issues": list(issues)}
    if quotes is not None:
        body["quotes"] = list(quotes)
    return lambda prompt: json.dumps(body)


def test_verified_quote_passes():
    """(e) ok=true with an exact (whitespace-normalised) source quote → passes with require_quotes."""
    rev = _says(True, quotes=["An offer may be revoked at any time before acceptance."])
    v = review_doctrine(SOURCE, "Offers can be revoked before acceptance.", rev, require_quotes=True)
    assert v.ok is True, v
    assert v.quotes == ["An offer may be revoked at any time before acceptance."]
    print("  (e) verified quote (whitespace-normalised): PASS")


def test_fabricated_quote_fails():
    """(f) ok=true with a quote that is not in the source → fail closed."""
    rev = _says(True, quotes=["An offer may never be revoked once made."])
    v = review_doctrine(SOURCE, "Offers are irrevocable.", rev, require_quotes=True)
    assert v.ok is False, v
    assert v.issues and v.issues[0].startswith("unverifiable source quote"), v.issues
    print("  (f) fabricated quote fails: PASS")


def test_one_bad_quote_among_good_fails():
    """(g) one verifiable + one fabricated quote → fail closed."""
    rev = _says(True, quotes=["A contract requires offer, acceptance and consideration.",
                              "Consideration must be adequate."])
    v = review_doctrine(SOURCE, "x", rev, require_quotes=True)
    assert v.ok is False, v
    print("  (g) mixed good+fabricated quotes fail: PASS")


def test_missing_quotes_fail_when_required():
    """(h) ok=true with no quotes (absent or empty) → fail when quotes are required."""
    for rev in (_says(True), _says(True, quotes=[])):
        v = review_doctrine(SOURCE, "x", rev, require_quotes=True)
        assert v.ok is False and v.issues == ["no supporting source quotes"], v
    print("  (h) missing quotes fail when required: PASS")


def test_multiline_quote_with_raw_newline():
    """(h2) a quote spanning the source's line break, emitted with a RAW newline inside the JSON string, verifies."""
    raw = '{"ok": true, "issues": [], "quotes": ["acceptance and consideration.\nAn offer may be revoked"]}'
    assert "\n" in raw
    v = review_doctrine(SOURCE, "x", lambda p: raw, require_quotes=True)
    assert v.ok is True, v
    print("  (h2) multi-line quote with raw newline verifies: PASS")


def test_too_short_quote_fails():
    """(i) a trivially short quote (e.g. 'offer') does not count as support."""
    v = review_doctrine(SOURCE, "x", _says(True, quotes=["offer"]), require_quotes=True)
    assert v.ok is False, v
    print("  (i) too-short quote fails: PASS")


def test_bad_quotes_shape_fail_closed():
    """(j) quotes present but not a list of strings → unparseable, fail closed."""
    for raw in ('{"ok": true, "issues": [], "quotes": "A contract requires offer"}',
                '{"ok": true, "issues": [], "quotes": [1, 2]}'):
        v = parse_verdict(raw)
        assert v.ok is False and v.issues == ["unparseable reviewer output"], v
    print("  (j) malformed quotes fail closed: PASS")


def test_ok_false_unchanged_by_quote_rule():
    """(k) ok=false keeps the reviewer's own issues under require_quotes."""
    v = review_doctrine(SOURCE, "x", _says(False, issues=["reversed the rule"]), require_quotes=True)
    assert v.ok is False and v.issues == ["reversed the rule"], v
    print("  (k) ok=false issues preserved: PASS")


def test_unverified_quotes_helper():
    """(l) unverified_quotes returns only the bad ones."""
    good = "A contract requires offer, acceptance and consideration."
    bad = "A contract requires a deed."
    assert unverified_quotes(SOURCE, [good, bad]) == [bad]
    print("  (l) unverified_quotes helper: PASS")


def test_distractor_prompt_contains_parts():
    """(m) build_distractor_prompt contains source, question, option and teaching."""
    p = build_distractor_prompt("SRC-1", "Q-2", "OPT-3", "TEACH-4")
    for part in ("SRC-1", "Q-2", "OPT-3", "TEACH-4"):
        assert part in p, part
    assert "false law" in p.lower() and '"quotes"' in p
    print("  (m) distractor prompt contains all parts: PASS")


def _fake_distractor_reviewer(prompt: str) -> str:
    """Fake reviewer: blocks a distractor whose text asserts an invented rule as fact."""
    option = prompt.split("DISTRACTOR (the wrong option, including any story text):\n", 1)[1].split("\n\nTEACHING", 1)[0]
    if "it is settled law that" in option.lower():
        return json.dumps({"ok": False, "issues": ["states false law as fact: offers are irrevocable"], "quotes": []})
    return json.dumps({"ok": True, "issues": [],
                       "quotes": ["An offer may be revoked at any time before acceptance."]})


def test_distractor_false_law_as_fact_fails():
    """(n) a distractor that states false law as fact → fail on the fake reviewer."""
    v = review_distractor(
        SOURCE, "Can Ann revoke her offer before Ben accepts?",
        "No. It is settled law that every offer is irrevocable once made.",
        "Wrong: the source says an offer may be revoked before acceptance.",
        _fake_distractor_reviewer)
    assert v.ok is False, v
    assert any("false law" in i for i in v.issues), v.issues
    print("  (n) distractor stating false law as fact fails: PASS")


def test_distractor_clean_passes():
    """(o) a clean distractor with a verified quote passes."""
    v = review_distractor(
        SOURCE, "Can Ann revoke her offer before Ben accepts?",
        "No, Ann thinks her offer binds her as soon as she makes it.",
        "Wrong: the source says an offer may be revoked before acceptance.",
        _fake_distractor_reviewer)
    assert v.ok is True, v
    print("  (o) clean distractor passes: PASS")


def test_distractor_requires_quotes():
    """(p) pass 2 always requires quotes: ok=true without quotes or with a fabricated one fails."""
    args = (SOURCE, "Q", "opt", "teach")
    assert review_distractor(*args, _says(True)).ok is False
    assert review_distractor(*args, _says(True, quotes=["Offers are irrevocable by statute."])).ok is False
    assert review_distractor(*args, lambda p: "garbage").ok is False
    print("  (p) distractor quotes always required: PASS")


if __name__ == "__main__":
    test_ok_true()
    test_fenced_json()
    test_garbage_fail_closed()
    test_build_prompt_contains_texts()
    test_verified_quote_passes()
    test_fabricated_quote_fails()
    test_one_bad_quote_among_good_fails()
    test_missing_quotes_fail_when_required()
    test_multiline_quote_with_raw_newline()
    test_too_short_quote_fails()
    test_bad_quotes_shape_fail_closed()
    test_ok_false_unchanged_by_quote_rule()
    test_unverified_quotes_helper()
    test_distractor_prompt_contains_parts()
    test_distractor_false_law_as_fact_fails()
    test_distractor_clean_passes()
    test_distractor_requires_quotes()
    print("OK")
