import sys
import os

# Allow sibling import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from self_contained import check_self_contained, passes

if __name__ == "__main__":
    # (a) Bundle whose only fetch is relative → ok True, no hits
    bundle_a = "fetch('/api/catalogue/docket')"
    result_a = check_self_contained(bundle_a)
    assert result_a.ok is True, f"Case a: expected ok=True, got {result_a}"
    assert result_a.hits == [], f"Case a: expected no hits, got {result_a.hits}"

    # (b) Bundle with fetch to api.anthropic.com → ok False, hit mentions anthropic
    bundle_b = "fetch('https://api.anthropic.com/v1/messages', {method: 'POST'})"
    result_b = check_self_contained(bundle_b)
    assert result_b.ok is False, f"Case b: expected ok=False, got {result_b}"
    assert any("anthropic" in h.lower() for h in result_b.hits), \
        f"Case b: expected hit mentioning anthropic, got {result_b.hits}"

    # (c) Bundle mentioning openai.com in a script src → ok False
    bundle_c = '<script src="https://openai.com/widget.js"></script>'
    result_c = check_self_contained(bundle_c)
    assert result_c.ok is False, f"Case c: expected ok=False, got {result_c}"
    assert any("openai" in h.lower() for h in result_c.hits), \
        f"Case c: expected hit mentioning openai, got {result_c.hits}"

    # (d) extra_forbidden catches custom host
    bundle_d = "fetch('https://evil.example/x')"
    result_d = check_self_contained(bundle_d, extra_forbidden=["evil.example"])
    assert result_d.ok is False, f"Case d: expected ok=False, got {result_d}"
    assert any("evil.example" in h for h in result_d.hits), \
        f"Case d: expected hit mentioning evil.example, got {result_d.hits}"

    # (e) Empty bundle → ok True
    bundle_e = ""
    result_e = check_self_contained(bundle_e)
    assert result_e.ok is True, f"Case e: expected ok=True, got {result_e}"
    assert result_e.hits == [], f"Case e: expected no hits, got {result_e.hits}"

    # Also test passes() helper
    assert passes("fetch('/local')") is True
    assert passes("fetch('https://api.openai.com/v1/chat')") is False

    print("OK")
