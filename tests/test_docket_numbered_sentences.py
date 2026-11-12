"""WRITER v2.1: checks cite numbered source sentence ids and code inserts the exact quote.

The PIL wk4 pilot rejected 4/4 v2 drafts because the local Coder paraphrased or stitched its "verbatim" quotes. Now
the SOURCES are numbered sentence by sentence ([S1.47]), the writer cites an id (or a range of up to 3), and
docketgen.numbered_sentence_checks copies the source text in. studio.grounding then verifies it unchanged (6-word
minimum, no reuse or near-duplicates). Synthetic fixtures only: no course text.
"""
import copy
import json

import docketgen
import relevance
from studio import grounding

MESSY = ("Under Art. 5 TEU the Union acts only within the competences conferred on it.\n"
         "See Case C-6/90 Francovich, para. 35, on state liability for breaches.\n"
         "The Court in Van Gend en Loos v. Netherlands held that the Treaty creates rights for individuals.\n\n"
         "Slide 4\n"
         "- direct effect of Treaty articles\n"
         "- supremacy of EU law over national law\n"
         "1. First the court checks whether the provision is clear and precise.\n"
         "2) Then it checks whether the provision is unconditional, e.g. needs no further measure.\n"
         "A State that breaches EU law may be liable in damages to\n"
         "individuals who suffer loss as a result.  Liability needs a sufficiently serious breach!\n"
         "J. Smith argues that the test is too strict for national courts to apply.")
KEYED = {"S1": {"name": "wk3 slides.txt", "role": "lecture", "text": MESSY},
         "S2": {"name": "wk3 WG.txt", "role": "wg", "text": "The working group applied the Francovich test to the facts of the case. "
                                                             "It found the breach sufficiently serious in the circumstances."}}


def _sents(key="S1"):
    t = KEYED[key]["text"]
    return [t[a:b] for a, b in docketgen.sentence_spans(t)]


# ------------------------------------------------------------------------------------- splitting and numbering

def test_sentence_spans_respect_legal_abbreviations_lists_and_wrapped_lines():
    s = _sents()
    assert s[0] == "Under Art. 5 TEU the Union acts only within the competences conferred on it."
    assert s[1] == "See Case C-6/90 Francovich, para. 35, on state liability for breaches."
    assert s[2].startswith("The Court in Van Gend en Loos v. Netherlands") and s[2].endswith("individuals.")
    assert s[3:6] == ["Slide 4", "- direct effect of Treaty articles", "- supremacy of EU law over national law"]
    assert s[6] == "1. First the court checks whether the provision is clear and precise."
    assert s[7].startswith("2) Then") and "e.g. needs" in s[7]
    assert s[8] == "A State that breaches EU law may be liable in damages to\nindividuals who suffer loss as a result."
    assert s[9] == "Liability needs a sufficiently serious breach!"
    assert s[10].startswith("J. Smith argues")
    assert len(s) == 11


def test_spans_are_ordered_trimmed_and_cover_every_word():
    t = KEYED["S1"]["text"]
    spans = docketgen.sentence_spans(t)
    assert all(a < b and t[a:b] == t[a:b].strip() for a, b in spans)
    assert all(b1 <= a2 for (_, b1), (a2, _) in zip(spans, spans[1:]))
    assert " ".join(" ".join(t[a:b].split()) for a, b in spans).split() == t.split()


def test_a_long_run_without_full_stops_is_cut_at_a_space():
    t = " ".join(["word"] * 400)
    spans = docketgen.sentence_spans(t)
    assert len(spans) > 1 and all(b - a <= docketgen.MAX_SENTENCE_CHARS for a, b in spans)
    assert " ".join(t[a:b] for a, b in spans).split() == t.split()


def test_sources_block_numbers_every_shown_sentence_by_its_place_in_the_whole_file():
    block = docketgen.ranked_sources_block(KEYED, "", relevance.rank)
    assert block.startswith("SOURCES:\n") and 'key="S1"' in block and 'key="S2"' in block
    assert "[S1.1] Under Art. 5 TEU the Union acts only within the competences conferred on it." in block
    assert "[S1.9] A State that breaches EU law may be liable in damages to individuals who suffer loss as a result." in block
    assert "[S2.2] It found the breach sufficiently serious in the circumstances." in block
    assert docketgen.shown_sentence_ids(block) == {("S1", n) for n in range(1, 12)} | {("S2", 1), ("S2", 2)}


def test_ranked_sources_keep_whole_relevant_sentences_with_whole_file_ids():
    filler = "\n\n".join("Paragraph %d is about tax and farming subsidies in the region. " % i * 20 for i in range(60))
    key = "Opinio juris is the belief that a practice is legally required."
    big = filler + "\n\n" + key + "\n\n" + filler
    keyed = {"S1": {"name": "reader.txt", "text": big}, "S2": {"name": "wg.txt", "text": "Short WG note on custom."}}
    block = docketgen.ranked_sources_block(keyed, "opinio juris belief legally required practice", relevance.rank)
    n = next(i for i, (a, b) in enumerate(docketgen.sentence_spans(big), 1) if big[a:b] == key)
    assert f"[S1.{n}] {key}" in block and "[…]" in block and "[S2.1] Short WG note on custom." in block
    assert block.count("Paragraph") < big.count("Paragraph")
    shown = docketgen.shown_sentence_ids(block)
    assert ("S1", n) in shown


def test_v1_sources_block_is_unchanged_and_unnumbered():
    assert "[S1.1]" not in docketgen.sources_block(KEYED) and MESSY in docketgen.sources_block(KEYED)


# ------------------------------------------------------------------------------------- resolving ids to quotes

def _resolve(checks, shown="all"):
    shown = docketgen.shown_sentence_ids(docketgen.ranked_sources_block(KEYED, "", None)) if shown == "all" else shown
    return docketgen.numbered_sentence_checks(checks, KEYED, shown)


def test_one_id_becomes_the_exact_sentence_and_its_source_cite_and_a_typed_quote_is_discarded():
    out, bad = _resolve([{"claim": "c", "sentence": "S1.9", "cites": ["S2"], "quote": "a paraphrase the model typed"}])
    assert bad == []
    assert out[0]["quote"] == "A State that breaches EU law may be liable in damages to individuals who suffer loss as a result."
    assert out[0]["cites"] == ["S1"] and out[0]["sentence"] == "S1.9" and "unresolved" not in out[0]
    assert " ".join(out[0]["quote"].split()) in " ".join(MESSY.split())


def test_a_range_is_one_contiguous_slice_of_the_source():
    t, sp = MESSY, docketgen.sentence_spans(MESSY)
    for ref in ("S1.9-S1.10", "S1.9-10", "[S1.9–S1.10]", ["S1.9", "S1.10"], "S1.9 to S1.10"):
        out, bad = _resolve([{"claim": "c", "sentence": ref}])
        assert bad == [], ref
        assert out[0]["quote"] == " ".join(t[sp[8][0]:sp[9][1]].split()) and out[0]["sentence"] == "S1.9-S1.10"


def test_bad_ids_are_problems_never_quotes():
    cases = {
        "missing": ({"claim": "c", "quote": "Liability needs a sufficiently serious breach"}, 'no "sentence"'),
        "malformed": ({"claim": "c", "sentence": "sentence nine"}, "is not a sentence id"),
        "unknown key": ({"claim": "c", "sentence": "S7.1"}, "S7 is not a source key"),
        "out of range": ({"claim": "c", "sentence": "S1.99"}, "not a sentence shown"),
        "zero": ({"claim": "c", "sentence": "S1.0"}, "not a sentence shown"),
        "reversed": ({"claim": "c", "sentence": "S1.10-S1.9"}, "runs backwards"),
        "too long": ({"claim": "c", "sentence": "S1.6-S1.9"}, "is 4 sentences"),
        "two sources": ({"claim": "c", "sentence": "S1.9-S2.1"}, "crosses two sources"),
        "gappy list": ({"claim": "c", "sentence": ["S1.1", "S1.2", "S1.9"]}, "is not a sentence id"),
    }
    for name, (chk, msg) in cases.items():
        out, bad = _resolve([chk])
        assert len(bad) == 1 and msg in bad[0], (name, bad)
        assert out[0]["unresolved"] is True and "quote" not in out[0], name


def test_an_id_the_writer_was_not_shown_is_rejected():
    out, bad = docketgen.numbered_sentence_checks([{"claim": "c", "sentence": "S1.9"}], KEYED, {("S1", 1)})
    assert "not a sentence shown" in bad[0]
    out, bad = docketgen.numbered_sentence_checks([{"claim": "c", "sentence": "S1.9"}], KEYED, None)   # no filter
    assert bad == []


def test_a_sentence_cannot_support_two_checks_even_padded_with_neighbours():
    out, bad = _resolve([{"claim": "a", "sentence": "S1.9"}, {"claim": "b", "sentence": "S1.8-S1.10"}])
    assert len(bad) == 1 and "check 2" in bad[0] and "repeats a sentence" in bad[0]


def test_grounding_rules_still_apply_to_the_copied_text():
    out, bad = _resolve([{"claim": "a", "sentence": "S1.4"}])                      # "Slide 4": under 6 words
    assert bad == []
    probs = grounding.check_problems(out, KEYED)
    assert len(probs) == 1 and "S1.4" in probs[0] and "under 6 words" in probs[0]
    out, bad = _resolve([{"claim": "a", "sentence": "S1.9"}, {"claim": "b", "sentence": "S1.4"}, {"claim": "c", "sentence": "S2.1"}])
    assert bad == [] and [i for i, p in enumerate(grounding.check_problems(out, KEYED)) if "S1.4" in p] == [0]
    unresolved, bad = _resolve([{"claim": "a", "sentence": "S1.99"}, {"claim": "b", "sentence": "S1.9"}])
    assert grounding.check_problems(unresolved, KEYED) == []            # the id problem is reported once, by the resolver
    assert grounding.grounding_share(unresolved, KEYED) == 0.5


def test_every_shown_sentence_and_short_range_verifies_against_its_source():
    """Grounding by construction: no allowed id or range can ever fail as "not in" its source."""
    for key in KEYED:
        n = len(docketgen.sentence_spans(KEYED[key]["text"]))
        for a in range(1, n + 1):
            for b in range(a, min(n, a + docketgen.MAX_RANGE_SENTENCES - 1) + 1):
                out, bad = _resolve([{"claim": "c", "sentence": f"{key}.{a}-{key}.{b}"}])
                assert bad == [], (key, a, b)
                assert not any("is not in" in p for p in grounding.check_problems(out, KEYED)), (key, a, b)


def test_a_leaked_inline_sentence_id_counts_as_its_source_cite():
    g = docketgen.collapse_sentence_cites({"t": "It is unilateral [S1.4] and serious [S1.9-S1.10].",
                                           "checks": [{"claim": "x [S1.2]", "sentence": "S1.2"}]})
    assert g["t"] == "It is unilateral [S1] and serious [S1]."
    assert g["checks"][0] == {"claim": "x [S1]", "sentence": "S1.2"}


# ------------------------------------------------------------------------------------- end to end, fake model

SRC = ("A reservation is a unilateral statement made by a State when signing a treaty. "
       "Opinio juris is the belief that a practice is legally required. "
       "State practice must be general and consistent.")
E2E = {"S1": {"name": "wk2.txt", "role": "lecture", "text": SRC}}


def _game(checks):
    from test_docketgen_v2 import inter
    g = inter("A")
    g["checks"] = checks
    return g


def _fake(replies, log):
    def fn(role, system, user, max_tokens):
        log.append((role, user))
        return json.dumps(replies.pop(0)), "mlx-community/Qwen3-coder", "http://127.0.0.1:8080/v1"
    return fn


def _draft(replies):
    log = []
    prefix = "COURSE BRIEF:\nx\n\n" + docketgen.ranked_sources_block(E2E, "", None)
    out = docketgen.write_draft_v2(_fake(list(replies), log), system="BRIEF", prefix=prefix, label="week 2", mix="A",
                                   keyed=E2E, quote_problems=grounding.check_problems)
    return out, log


IDS = [{"claim": "reservations are unilateral", "sentence": "S1.1"},
       {"claim": "custom needs a belief in obligation", "sentence": "[S1.2]"},
       {"claim": "practice must be general", "sentence": "S1.3"}]


def test_end_to_end_v2_compile_with_a_fake_model_citing_ids():
    out, log = _draft([_game(copy.deepcopy(IDS))])
    assert [r for r, _ in log] == ["write"]
    task = log[0][1]
    assert "[S1.2] Opinio juris is the belief that a practice is legally required." in task
    assert '"sentence": "S1.47"' in task and "Do NOT type quotes" in task and "word for word" not in task
    checks = out["game"]["checks"]
    spans = docketgen.sentence_spans(SRC)
    assert [c["quote"] for c in checks] == [SRC[a:b] for a, b in spans]
    assert [c["sentence"] for c in checks] == ["S1.1", "S1.2", "S1.3"] and all(c["cites"] == ["S1"] for c in checks)
    assert grounding.grounding_share(checks, E2E) == 1.0 and not any("unresolved" in c for c in checks)
    assert out["prompt_version"] == "writer-v2.3"
    assert docketgen.validate_v2(out["game"], E2E.keys(), "A") == []


def test_end_to_end_paraphrased_quotes_are_repaired_into_ids():
    """The pilot's failure: the model types a stitched paraphrase. It is not accepted as a quote; the repair round
    asks for ids, and an id-citing reply passes."""
    stitched = [{"claim": c["claim"], "cites": ["S1"], "quote": "a reservation is a statement a State makes alone when signing"}
                for c in IDS]
    out, log = _draft([_game(stitched), _game(copy.deepcopy(IDS))])
    assert [r for r, _ in log] == ["write", "repair"]
    assert 'check 1 has no "sentence"' in log[1][1] and "do not type a quote" in log[1][1]
    assert grounding.grounding_share(out["game"]["checks"], E2E) == 1.0


def test_end_to_end_bad_ids_after_repair_fail_the_draft():
    bad = copy.deepcopy(IDS); bad[0]["sentence"] = "S1.99"
    try:
        _draft([_game(bad), _game(bad), _game(bad)])   # write, repair, targeted repair
    except ValueError as e:
        assert "S1.99" in str(e)
    else:
        raise AssertionError("an unknown sentence id after the repair round must fail the draft")
    reused = copy.deepcopy(IDS); reused[2]["sentence"] = "S1.1-S1.2"
    out, log = _draft([_game(reused), _game(copy.deepcopy(IDS))])
    assert "repeats a sentence" in log[1][1]
