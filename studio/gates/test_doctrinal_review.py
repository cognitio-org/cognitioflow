"""Self-contained tests for doctrinal_review gate — no pytest required."""

import sys
import os

# Ensure the repo root is on sys.path so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

from studio.gates.doctrinal_review import build_prompt, review_doctrine, parse_verdict, DoctrineVerdict


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
        return '```json\n{"ok": false, "issues": ["invented a defence"]}\n```'

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


if __name__ == "__main__":
    test_ok_true()
    test_fenced_json()
    test_garbage_fail_closed()
    test_build_prompt_contains_texts()
    print("OK")
