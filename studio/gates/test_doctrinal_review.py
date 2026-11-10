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


# Reconstructed reviewer probe: a thinking model drafts an ok:true verdict (with a
# genuinely verifiable SOURCE quote) inside its reasoning, then changes its mind.
# Before the fix, the first JSON object (the draft) won.
PROBE_DRAFT = '{"ok": true, "issues": [], "quotes": ["An offer may be revoked at any time before acceptance."]}'
PROBE_FINAL = '{"ok": false, "issues": ["reversed the rule: the source makes offers revocable"]}'
PROBE = ("<think>\nDraft verdict: " + PROBE_DRAFT +
         "\nWait: the generated text says offers are irrevocable, which reverses the source.\n</think>\n"
         + PROBE_FINAL)


def test_ok_true_with_issues_fails():
    """(q) ok=true but a non-empty issues list is contradictory → fail closed, issues kept."""
    v = parse_verdict('{"ok": true, "issues": ["invented an element"]}')
    assert v.ok is False, v
    assert "invented an element" in v.issues, v.issues
    # also without require_quotes, and with a verifiable quote attached
    rev = _says(True, issues=["invented an element"],
                quotes=["An offer may be revoked at any time before acceptance."])
    assert review_doctrine(SOURCE, "x", rev).ok is False
    assert review_doctrine(SOURCE, "x", rev, require_quotes=True).ok is False
    assert review_distractor(SOURCE, "Q", "opt", "teach", rev).ok is False
    print("  (q) ok=true with issues fails: PASS")


def test_think_draft_cannot_win():
    """(r) a draft ok:true inside <think>...</think> never beats the final verdict."""
    v = parse_verdict(PROBE)
    assert v.ok is False, v
    assert v.issues == ["reversed the rule: the source makes offers revocable"], v.issues
    assert v.raw == PROBE  # raw is the untouched reviewer output
    for req in (False, True):
        assert review_doctrine(SOURCE, "Offers are irrevocable.", lambda p: PROBE, require_quotes=req).ok is False
    assert review_distractor(SOURCE, "Q", "opt", "teach", lambda p: PROBE).ok is False
    # tag case does not matter
    assert parse_verdict(PROBE.replace("think>", "THINK>")).ok is False
    print("  (r) <think> draft cannot win: PASS")


def test_orphan_close_think_drops_prefix():
    """(s) an orphan </think> (opening tag eaten by the chat template) drops everything before it."""
    raw = "Draft verdict: " + PROBE_DRAFT + "\nHmm, no.\n</think>\n" + PROBE_FINAL
    v = parse_verdict(raw)
    assert v.ok is False and v.issues == ["reversed the rule: the source makes offers revocable"], v
    print("  (s) orphan </think> drops prefix: PASS")


def test_reasoning_only_is_unparseable():
    """(t) reasoning with no final verdict, or an unclosed <think>, fails closed."""
    for raw in ("<think>" + PROBE_DRAFT + "</think>",
                PROBE_DRAFT + "</think>   ",
                "<think>still drafting " + PROBE_DRAFT):
        v = parse_verdict(raw)
        assert v.ok is False and v.issues == ["unparseable reviewer output"], (raw, v)
    print("  (t) reasoning-only / unclosed <think> fails closed: PASS")


def test_think_stripped_then_good_verdict_passes():
    """(u) a genuine final ok:true after reasoning still passes with a verified quote."""
    raw = "<think>checking " + PROBE_FINAL + "</think>" + PROBE_DRAFT
    v = review_doctrine(SOURCE, "Offers can be revoked before acceptance.", lambda p: raw, require_quotes=True)
    assert v.ok is True, v
    print("  (u) final ok:true after reasoning passes: PASS")


TYPO_SOURCE = ("The court held that the \u201cpostal rule\u201d applies \u2013 acceptance is "
               "complete on posting \u2014 unless the offeror\u2019s terms exclude it.")


def test_typographic_quotes_and_dashes_normalised():
    """(v) curly quotes / en-em dashes / case differences between quote and source still verify."""
    quotes = ['the "postal rule" applies - acceptance is complete on posting',
              "ACCEPTANCE IS COMPLETE ON POSTING - UNLESS THE OFFEROR'S TERMS",
              "the \u2018postal rule\u2019 applies \u2014 acceptance"]
    assert unverified_quotes(TYPO_SOURCE, quotes) == [quotes[2]]  # single curly != double straight
    # straight in source, curly in quote
    assert unverified_quotes('the offeror\'s "terms" - here apply', ["offeror\u2019s \u201cterms\u201d \u2013 here"]) == []
    v = review_doctrine(TYPO_SOURCE, "x", _says(True, quotes=quotes[:2]), require_quotes=True)
    assert v.ok is True, v
    assert v.quotes == quotes[:2]  # original strings are kept, not the normalised forms
    print("  (v) typographic quotes/dashes + case normalised: PASS")


def test_normalisation_does_not_admit_fabrication():
    """(w) normalisation never lets a fabricated or too-short quote through."""
    bad = ["The \u201cPostal Rule\u201d never applies \u2013 acceptance is complete on receipt",
           "\u201cPOSTAL RULE\u201d",          # 13 chars incl. quotes: in source, long enough
           "\u201cpostal\u201d",                # 8 chars after normalisation: too short
           "acceptance is complete on posting\u2014 unless the OFFEREE"]
    assert unverified_quotes(TYPO_SOURCE, bad) == [bad[0], bad[2], bad[3]]
    print("  (w) normalisation does not admit fabrication: PASS")


def test_reviewer_probe_strings_from_s5():
    """(x) the exact probe strings from the S5 runtime review (studio/test_runtime.py on #191):
    parse_verdict alone (no transport stripping) must never let the scratch ok:true win."""
    closed = '<think>scratch: {"ok": true, "issues": []}</think>\n{"ok": false, "issues": ["x"]}'
    orphan = 'scratch: {"ok": true, "issues": []}\n</think>\n\n{"ok": false, "issues": ["y"]}'
    unterminated = '<think>{"ok": true, "issues": []} still thinking'
    assert parse_verdict(closed).issues == ["x"] and parse_verdict(closed).ok is False
    assert parse_verdict(orphan).issues == ["y"] and parse_verdict(orphan).ok is False
    v = parse_verdict(unterminated)
    assert v.ok is False and v.issues == ["unparseable reviewer output"], v
    print("  (x) S5 reviewer probe strings: PASS")


# --- hardening-1: header quotes (finding 3) and multiple / nested verdicts (finding 4) ---

# The docket adapter builds SOURCE as "[KEY] file" header lines, each followed by that file's text.
HDR_SOURCE = ("[S1] week3-lecture-notes.pdf\n"
              "A contract requires offer, acceptance and consideration.\n\n"
              "[S2] week3-reader-chapter-2.pdf\n"
              "An offer may be revoked at any time before acceptance.")


def test_header_quote_cannot_verify():
    """(y) quoting the adapter's own "[Sn] file" header line never counts as support."""
    for q in ("[S1] week3-lecture-notes.pdf", "week3-lecture-notes.pdf", "[S2] week3-reader-chapter-2.pdf",
              "week3-lecture-notes.pdf\nA contract requires"):
        assert unverified_quotes(HDR_SOURCE, [q]) == [q], q
        v = review_doctrine(HDR_SOURCE, "x", _says(True, quotes=[q]), require_quotes=True)
        assert v.ok is False and v.issues[0].startswith("unverifiable source quote"), (q, v)
        assert review_distractor(HDR_SOURCE, "Q", "opt", "teach", _says(True, quotes=[q])).ok is False, q
    # a header-shaped line at the very start of the source (offset 0) is stripped too
    assert unverified_quotes("[S7] notes.pdf\nbody text here", ["[S7] notes.pdf"]) == ["[S7] notes.pdf"]
    print("  (y) header-line quotes cannot verify: PASS")


def test_quote_cannot_stitch_across_sources():
    """(z) a quote joining the end of one source body to the start of the next does not verify."""
    stitched = "acceptance and consideration. An offer may be revoked"
    assert unverified_quotes(HDR_SOURCE, [stitched]) == [stitched]
    # each body on its own still verifies
    good = ["A contract requires offer, acceptance and consideration.",
            "An offer may be revoked at any time before acceptance."]
    assert unverified_quotes(HDR_SOURCE, good) == []
    v = review_doctrine(HDR_SOURCE, "x", _says(True, quotes=good), require_quotes=True)
    assert v.ok is True, v
    print("  (z) no quote stitched across sources: PASS")


def test_quote_needs_a_real_word():
    """(aa) a quote must carry a word of 4+ characters that is not a header word."""
    src = "[S1] offer-revocation.pdf\nSee s. 12(3)(a)-(b), 1999, p. 4: offer revocation is allowed before acceptance."
    no_word = "s. 12(3)(a)-(b), 1999, p. 4"
    header_words = "offer revocation"   # in the body, long enough, but every 4+ word is a header word
    assert unverified_quotes(src, [no_word]) == [no_word]
    assert unverified_quotes(src, [header_words]) == [header_words]
    # a body quote that shares words with the filename still verifies
    real = "offer revocation is allowed before acceptance"
    assert unverified_quotes(src, [real]) == []
    print("  (aa) quote needs a non-header word of 4+ chars: PASS")


def test_header_hook():
    """(ab) a caller can pass its own header-stripping hook; the default strips ^[Sn] lines."""
    src = "## FILE contracts.pdf\nA contract requires offer, acceptance and consideration."
    def hook(text):   # -> (source bodies, header lines)
        lines = text.split("\n")
        return ([ln for ln in lines if not ln.startswith("## FILE")], [ln for ln in lines if ln.startswith("## FILE")])
    assert unverified_quotes(src, ["## FILE contracts.pdf"]) == []                 # default hook leaves it alone
    assert unverified_quotes(src, ["## FILE contracts.pdf"], split_sources=hook) == ["## FILE contracts.pdf"]
    v = review_doctrine(src, "x", _says(True, quotes=["## FILE contracts.pdf"]), require_quotes=True,
                        split_sources=hook)
    assert v.ok is False, v
    print("  (ab) header-stripping hook: PASS")


OK_V = '{"ok": true, "issues": [], "quotes": ["An offer may be revoked at any time before acceptance."]}'
NO_V = '{"ok": false, "issues": ["reversed the rule"]}'


def test_conflicting_verdicts_fail_closed():
    """(ac) two top-level verdicts that disagree fail closed, in either order."""
    for raw in ("Draft: " + OK_V + " Final: " + NO_V, "Draft: " + NO_V + " Final: " + OK_V):
        v = parse_verdict(raw)
        assert v.ok is False, (raw, v)
        assert review_doctrine(SOURCE, "x", lambda p, raw=raw: raw, require_quotes=True).ok is False, raw
        assert review_distractor(SOURCE, "Q", "o", "t", lambda p, raw=raw: raw).ok is False, raw
    print("  (ac) conflicting verdicts fail closed: PASS")


def test_agreeing_verdicts_take_the_last():
    """(ad) repeated verdicts that agree are fine; the LAST one is used."""
    first = '{"ok": false, "issues": ["first"]}'
    last = '{"ok": false, "issues": ["last"]}'
    v = parse_verdict(first + "\n" + last)
    assert v.ok is False and v.issues == ["last"], v
    v = parse_verdict(OK_V + " then again " + OK_V)
    assert v.ok is True, v
    print("  (ad) agreeing verdicts: last wins: PASS")


def test_nested_verdict_rejected():
    """(ae) a verdict object nested inside another object is not a verdict."""
    for raw in ('{"verdict": ' + OK_V + '}',
                '{"verdict": {"ok": true, "issues": []}, "note": "x"}',
                '{"review": {"ok": true, "issues": []}} ' + '{"meta": 1}'):
        v = parse_verdict(raw)
        assert v.ok is False and v.issues == ["unparseable reviewer output"], (raw, v)
    print("  (ae) nested verdict rejected: PASS")


def test_braces_inside_strings_do_not_count():
    """(af) a verdict-looking string inside issues/quotes is not a second verdict."""
    raw = '{"ok": false, "issues": ["the draft said {\\"ok\\": true} but the rule is reversed"]}'
    v = parse_verdict(raw)
    assert v.ok is False and len(v.issues) == 1 and "reversed" in v.issues[0], v
    raw = '{"ok": true, "issues": [], "quotes": ["An offer may be revoked {at} any time"]}'
    assert parse_verdict(raw).ok is True
    # prose braces around a single real verdict are ignored
    assert parse_verdict("Using {braces} in prose. " + OK_V).ok is True
    print("  (af) braces inside strings / prose ignored: PASS")


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
    test_ok_true_with_issues_fails()
    test_think_draft_cannot_win()
    test_orphan_close_think_drops_prefix()
    test_reasoning_only_is_unparseable()
    test_think_stripped_then_good_verdict_passes()
    test_typographic_quotes_and_dashes_normalised()
    test_normalisation_does_not_admit_fabrication()
    test_reviewer_probe_strings_from_s5()
    test_header_quote_cannot_verify()
    test_quote_cannot_stitch_across_sources()
    test_quote_needs_a_real_word()
    test_header_hook()
    test_conflicting_verdicts_fail_closed()
    test_agreeing_verdicts_take_the_last()
    test_nested_verdict_rejected()
    test_braces_inside_strings_do_not_count()
    print("OK")
