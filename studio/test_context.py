"""Tests for studio/context.py, studio/grounding.py and studio/provenance.py (model-quality plan rungs 0-2).

Run:  python3 studio/test_context.py      Stdlib only, synthetic fixtures only (no course text), no network.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from studio import context, grounding, provenance  # noqa: E402

SPLIT = {"heldout": {"pil": ["3", "4"]}, "dev": {"pil": ["1", "2"]}}
CODER = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-DWQ"
THINKER = "mlx-community/Qwen3-30B-A3B-Thinking-2507-4bit"


# ------------------------------------------------------------------------------------------------ brief + layout

def test_brief_loads_and_is_hashed():
    text, h = context.load_brief()
    assert "CognitioFlow Game Studio" in text and len(h) == 16
    assert "wrong on purpose" in text.lower() and "quote" in text.lower()


def test_missing_or_empty_brief_refuses():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "brief.md"
        for content in (None, "   \n"):
            if content is not None:
                p.write_text(content)
            try:
                context.load_brief(p)
            except context.ContextError:
                continue
            raise AssertionError("an absent/empty brief must refuse")


def test_every_role_shares_a_byte_identical_prefix_and_task_is_last():
    ctx = {"course_brief": "Exam: problem questions.", "lexicon": "LEXICON (x):\n- \"a\": never write \"b\" instead"}
    src = "SOURCES:\n<source key=\"S1\">alpha</source>"
    msgs = [context.user_message(ctx, src, t) for t in ("TASK: write", "TASK: review", "TASK: revise")]
    prefix = context.shared_prefix(ctx, src)
    assert all(m.startswith(prefix) for m in msgs)
    m = msgs[0]
    assert m.index("COURSE BRIEF") < m.index("LEXICON") < m.index("SOURCES") < m.index("TASK: write")
    assert m.endswith("TASK: write")


def test_course_brief_stored_wins_and_draft_file_is_skipped():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "pil.md").write_text("STATUS: DRAFT - review\nExam: x")
        assert context.load_course_brief("pil", "From the DB", briefs_dir=Path(d)) == ("From the DB", "courses.tutor_prompt")
        text, src = context.load_course_brief("pil", "", briefs_dir=Path(d), allow_draft=False)
        assert text == "" and "skipped" in src
        text, src = context.load_course_brief("pil", "", briefs_dir=Path(d), allow_draft=True)
        assert "Exam: x" in text and "(DRAFT)" in src
        (Path(d) / "pil.md").write_text("Exam: reviewed")
        assert context.load_course_brief("pil", "", briefs_dir=Path(d), allow_draft=False)[0] == "Exam: reviewed"
    assert context.load_course_brief("../etc", "") == ("", "none")


def test_shipped_pil_brief_is_reviewed_and_used_by_default():
    # Matej approved the filled brief on 2026-11-12, so the DRAFT mark is gone and the writer uses it.
    text, src = context.load_course_brief("pil", "", allow_draft=False)
    assert src == "briefs/pil.md" and "Method:" in text
    assert "TO FILL" not in text and context.DRAFT_MARK not in text


def test_lexicon_block_is_generated_from_the_approved_file():
    text, version = context.lexicon_block("pil")
    assert version == "pil-v2" and '"opinio juris": never write' in text and "opinion of jurists" in text
    assert context.lexicon_block("nope") == ("", "none")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "bad.json").write_text("{\"version\": \"v\", \"terms\": []}")
        try:
            context.lexicon_block("bad", lexicon_dir=Path(d))
        except context.ContextError:
            pass
        else:
            raise AssertionError("malformed lexicon must refuse")


# ------------------------------------------------------------------------------------------------ split + exemplars

def test_split_is_locked_and_pil_week_2_is_dev():
    s = context.load_split()
    assert s["dev"]["pil"] and "2" in s["dev"]["pil"] and "2" not in s["heldout"]["pil"]
    assert sum(len(v) for v in s["heldout"].values()) == 6
    assert context.split_of("pil", "2") == "dev"
    assert context.split_of("pil", "4") == "heldout"
    assert context.split_of("pil", "2,4", SPLIT) == "heldout"        # touching a held-out week = held-out
    assert context.split_of("pil", "all", SPLIT) == "heldout"
    assert context.split_of("pil", "9", SPLIT) == "unassigned"


def _ex(**kw):
    base = {"author": "matej", "edit_assisted": False, "provenance": "clean", "card": {"overall_pass": True},
            "course": "pil", "week": "1", "game": {"rounds": []}, "mix": "A"}
    base.update(kw)
    return base


def test_exemplar_rules_fail_closed():
    assert context.exemplar_problems(_ex(), SPLIT) == []
    assert context.exemplar_problems(_ex(author="unknown"), SPLIT)
    assert context.exemplar_problems(_ex(author="claude"), SPLIT)
    assert context.exemplar_problems(_ex(edit_assisted=None), SPLIT)          # unknown is not false
    assert context.exemplar_problems(_ex(provenance="tainted"), SPLIT)
    assert context.exemplar_problems(_ex(card={"overall_pass": "true"}), SPLIT)
    assert context.exemplar_problems(_ex(week="4"), SPLIT)                    # held-out week
    assert context.exemplar_problems(_ex(week="9"), SPLIT)                    # unassigned week
    assert context.exemplar_problems("x", SPLIT)


def test_exemplar_loader_caps_and_spreads_mixes():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        idx = []
        for i, (mix, ok) in enumerate([("A", True), ("A", True), ("B", True), ("C", False), ("D", True)]):
            (d / f"e{i}.json").write_text(json.dumps(_ex(mix=mix, author="matej" if ok else "unknown")))
            idx.append({"id": f"e{i}", "file": f"e{i}.json", "course": "pil"})
        idx.append({"id": "other", "file": "e0.json", "course": "eu-law"})
        (d / "index.json").write_text(json.dumps(idx))
        got, rejected = context.load_exemplars("pil", exemplar_dir=d, split=SPLIT)
        assert [e["id"] for e in got] == ["e0", "e2", "e4"]                   # one per mix first, capped at 3
        assert [r[0] for r in rejected] == ["e3"]
        assert "EXAMPLE GAME 1 (mix A" in context.exemplar_block(got)


def test_shipped_exemplar_index_is_empty():
    got, rejected = context.load_exemplars("pil")
    assert got == [] and rejected == [] and context.exemplar_block(got) == ""


def test_load_bundles_everything_with_hashes():
    ctx = context.load({"tutor_prompt": "Exam: two problem questions."}, "pil", allow_draft=False)
    assert ctx["brief_hash"] and ctx["course_brief_source"] == "courses.tutor_prompt"
    assert ctx["lexicon_version"] == "pil-v2" and ctx["exemplars"] == [] and ctx["course_brief_hash"]


# ------------------------------------------------------------------------------------------------ grounding

KEYED = {"S1": {"text": "A reservation is a unilateral statement made by a State when signing a treaty."},
         "S2": {"text": "Opinio juris is the belief that a practice is legally required."}}


def test_a_verbatim_quote_in_the_cited_source_is_grounded():
    checks = [{"claim": "c", "cites": ["S1"], "quote": "a unilateral statement made by a State"}]
    assert grounding.check_problems(checks, KEYED) == []
    assert grounding.grounding_share(checks, KEYED) == 1.0


def test_typography_and_whitespace_are_forgiven_like_the_doctrine_gate():
    checks = [{"claim": "c", "cites": ["S2 p.3"], "quote": "Opinio  juris is the “belief” that a practice"}]
    # curly quotes do not appear in the source at all, so this one must fail; plain spacing differences must not
    assert grounding.check_problems(checks, KEYED)
    checks[0]["quote"] = "Opinio   juris is the belief\nthat a practice"
    assert grounding.check_problems(checks, KEYED) == []


def test_quote_from_the_wrong_key_missing_or_invented_fails():
    bad = [{"claim": "c", "cites": ["S2"], "quote": "a unilateral statement made by a State"},   # it is in S1
           {"claim": "c", "cites": ["S1"]},
           {"claim": "c", "cites": ["S1"], "quote": "reservations are void under jus cogens"},
           {"claim": "c", "cites": [], "quote": "a unilateral statement made by a State"}]
    probs = grounding.check_problems(bad, KEYED)
    assert len(probs) == 4 and "not in S2" in probs[0] and "no quote" in probs[1]
    assert grounding.grounding_share(bad + [{"cites": ["S1"], "quote": "a unilateral statement made by a State"}],
                                     KEYED) == 0.2
    assert grounding.check_problems([], KEYED) and grounding.grounding_share([], KEYED) == 0.0


def test_short_generic_reused_or_too_few_quotes_do_not_ground_a_claim():
    short = [{"claim": "reservations are always void", "cites": ["S1"], "quote": "made by a State"}]
    assert "too short" in grounding.check_problems(short, KEYED)[0]           # verifies in S1, but says nothing
    q = "a unilateral statement made by a State"
    reused = [{"claim": "x", "cites": ["S1"], "quote": q}, {"claim": "y", "cites": ["S1"], "quote": " " + q.upper()}]
    probs = grounding.check_problems(reused, KEYED)
    assert len(probs) == 1 and "reuses" in probs[0] and grounding.grounding_share(reused, KEYED) == 0.5
    trimmed = [{"claim": "x", "cites": ["S1"], "quote": "A reservation is a unilateral statement made by a State"},
               {"claim": "y", "cites": ["S1"], "quote": q},                                   # contained in the first
               {"claim": "z", "cites": ["S1"], "quote": "reservation is a unilateral statement made by"}]
    assert [("reuses" in p) for p in grounding.check_problems(trimmed, KEYED)] == [True, True]
    whole = "A reservation is a unilateral statement made by a State when signing a treaty."
    inner = [{"claim": "x", "cites": ["S1"], "quote": whole},
             {"claim": "y", "cites": ["S1"], "quote": "is a unilateral statement made by"}]  # Jaccard 6/11: containment
    assert ["reuses" in p for p in grounding.check_problems(inner, KEYED)] == [True]
    two = [{"claim": "x", "cites": ["S1"], "quote": q},
           {"claim": "y", "cites": ["S2"], "quote": "the belief that a practice is legally required"}]
    assert grounding.check_problems(two, KEYED) == []                                   # different sentences: fine
    one = [{"claim": "x", "cites": ["S1"], "quote": q}]
    assert grounding.check_problems(one, KEYED) == []
    assert "at least 3" in grounding.check_problems(one, KEYED, min_checks=3)[0]


# ------------------------------------------------------------------------------------------------ provenance

def _calls(*extra):
    return [{"role": "write", "model": CODER, "base": "http://127.0.0.1:8080/v1"},
            {"role": "review", "model": THINKER, "base": "http://127.0.0.1:8082/v1"}, *extra]


def _rec(calls, **kw):
    return provenance.record(course_id="76512042", week="2", split="dev", calls=calls, prompt_version="writer-v2",
                             brief_hash="abc", sampling={"temperature": 0.7}, **kw)


def test_clean_m4_calls_give_a_clean_private_record():
    r = _rec(_calls())
    assert r["provenance"] == "clean" and r["privacy"] == "private" and r["taint_reason"] == ""
    assert r["writer_model"] == CODER and r["reviewer_model"] == THINKER and len(r["config_hash"]) == 16
    for k in ("draft_id", "created_at", "split", "calls", "parent_id", "gate_verdicts", "human_label"):
        assert k in r


def test_any_closed_model_call_taints_the_row():
    for model in ("claude-sonnet-5", "gpt-6-luna", "gemini-3.8-flash", "some-local-thing"):
        r = _rec(_calls({"role": "revise", "model": model, "base": "http://127.0.0.1:8080/v1"}))
        assert r["provenance"] == "tainted" and "revise" in r["taint_reason"], model
    r = _rec(_calls({"role": "repair", "model": CODER, "base": "https://router.kernal.one/v1"}))
    assert r["provenance"] == "tainted" and "base" in r["taint_reason"]
    assert _rec([])["provenance"] == "tainted"


def test_deepseek_only_on_public_rows_and_taint_is_sticky():
    ds = {"role": "write", "model": "deepseek-chat", "base": "http://127.0.0.1:1/v1"}
    assert _rec([ds])["provenance"] == "tainted"
    assert _rec([ds], source_privacy=["public", "public"])["provenance"] == "clean"
    assert _rec([ds], source_privacy=["public", "private"])["privacy"] == "private"
    parent = _rec([{"role": "write", "model": "claude-x", "base": ""}])
    assert _rec(_calls(), parent=parent)["provenance"] == "tainted"
    assert _rec(_calls(), edit_assisted=True)["provenance"] == "tainted"


def test_verdicts_from_card():
    card = {"reviewer_model": THINKER, "gates": [{"name": "doctrine", "passed": True},
                                                 {"name": "retrieval", "passed": "true"},
                                                 {"name": "polish", "passed": False, "infra": "timeout"}]}
    v, m = provenance.verdicts_from_card(card)
    assert v == {"doctrine": "pass", "retrieval": "fail", "polish": "infra"} and m == {"doctrine": THINKER}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  {t.__name__}: PASS")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  {t.__name__}: FAIL — {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
