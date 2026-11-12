"""WRITER v2.2: a sentence id put where a SOURCE id belongs still counts as a citation of its source.

The real-model pilot on PR #212 failed a draft with "Cites sources that do not exist: S1.18, S1.20, S1.30, S1.31,
S1.9": the M4 Coder put sentence ids ("S1.18") in "cites" lists, and validate() read each as an unknown source key.
A sentence id or range (S1.18, [S1.18], S1.18-S1.20) in a cites list or an inline marker now normalises to its source
(S1); a check with no "sentence" field but a sentence id in "cites" is resolved by the sentence rules. Unknown sources
(S9, S9.4) and bad sentence ids are still rejected. Synthetic fixtures only: no course text.
"""
import copy
import json

import docketgen
from studio import docket_adapter, grounding

SRC = ("A reservation is a unilateral statement made by a State when signing a treaty. "
       "Opinio juris is the belief that a practice is legally required. "
       "State practice must be general and consistent.")
E2E = {"S1": {"name": "wk2.txt", "role": "lecture", "text": SRC},
       "S2": {"name": "wk2b.txt", "role": "wg", "text": "The working group applied the custom test to the facts of the case."},
       "S3": {"name": "wk2c.txt", "role": "reader", "text": "Reservations to human rights treaties raise special problems."}}


def _game(checks, round_cites=None):
    from test_docketgen_v2 import inter
    g = inter("A")
    g["checks"] = checks
    if round_cites is not None:
        for r in g["rounds"]:
            r["cites"] = list(round_cites)
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


# The pilot's shape: every check has its "sentence" AND repeats the id in "cites"; rounds cite sentence ids too.
PILOT = [{"claim": "reservations are unilateral", "sentence": "S1.1", "cites": ["S1.1"]},
         {"claim": "custom needs a belief in obligation", "sentence": "S1.2", "cites": ["[S1.2]"]},
         {"claim": "practice must be general", "sentence": "S1.3", "cites": ["S1.3"]}]


def test_pilot_shape_sentence_ids_in_cites_lists_pass_and_are_stored_as_source_keys():
    reply = _game(copy.deepcopy(PILOT), round_cites=["S1.1", "S1.2-S1.3"])
    out, log = _draft([reply, copy.deepcopy(reply)])
    assert [r for r, _ in log] == ["write"], log[-1][1][-600:]
    game = out["game"]
    assert docketgen.validate_v2(game, E2E.keys(), "A") == []
    quizzes = [s["quiz"] for s in game["scenes"] if s.get("quiz")]
    assert all(q["cites"] == ["S1"] for q in quizzes)
    assert all(o["cites"] == ["S1"] for q in quizzes for o in q.get("options") or [])
    assert [c["sentence"] for c in game["checks"]] == ["S1.1", "S1.2", "S1.3"]
    assert all(c["cites"] == ["S1"] for c in game["checks"])
    assert grounding.grounding_share(game["checks"], E2E) == 1.0


def test_validate_reads_a_sentence_id_or_range_in_a_cites_list_as_its_source():
    from test_docketgen_v2 import inter
    game, _ = docketgen.compile_game(inter("A"), "A")
    for q in (s["quiz"] for s in game["scenes"] if s.get("quiz")):
        q["cites"] = ["S1.18", "S1.18-S1.20", "S1.30-31", "[S1.9]"]
    game["checks"][0]["cites"] = ["S1.20"]
    assert not any("do not exist" in p for p in docketgen.validate(game, E2E.keys()))


def test_a_check_with_its_sentence_id_only_in_cites_is_resolved_by_the_sentence_rules():
    only_cites = [{"claim": c["claim"], "cites": [c["sentence"]]} for c in PILOT]
    out, log = _draft([_game(only_cites)])
    assert [r for r, _ in log] == ["write"]
    checks = out["game"]["checks"]
    assert [c["sentence"] for c in checks] == ["S1.1", "S1.2", "S1.3"]
    assert [c["quote"] for c in checks] == [SRC[a:b] for a, b in docketgen.sentence_spans(SRC)]
    assert all(c["cites"] == ["S1"] for c in checks)


def test_a_bad_sentence_id_in_cites_still_gets_the_sentence_rule_problem():
    bad = [{"claim": c["claim"], "cites": [c["sentence"]]} for c in PILOT]
    bad[0]["cites"] = ["S1.99"]
    checks, probs = docketgen.numbered_sentence_checks(bad, E2E, None)
    assert any("S1.99" in p and "not a sentence shown" in p for p in probs)
    assert checks[0].get("unresolved") and checks[0]["cites"] == ["S1"]   # one problem, not also "unknown source"


def test_unknown_sources_are_still_rejected_in_every_form():
    from test_docketgen_v2 import inter
    for bad in (["S9"], ["S9.4"], ["[S9.4-S9.5]"], ["S1.4-S2.5"]):
        game, _ = docketgen.compile_game(inter("A"), "A")
        game["scenes"][1]["quiz"]["cites"] = list(bad)
        probs = docketgen.validate(game, E2E.keys())
        assert any("do not exist" in p for p in probs), (bad, probs)
    g = _game(copy.deepcopy(PILOT))
    g["rounds"][0]["teaching"] = "it is wrong [S9.4]"
    g["rounds"][0]["options"][0]["teaching"] = "see [S9.4]"
    game, _ = docketgen.compile_game(docketgen.collapse_sentence_cites(g), "A")
    assert any("do not exist: S9" in p for p in docketgen.validate(game, E2E.keys()))
    checks, probs = docketgen.numbered_sentence_checks([{"claim": "x", "sentence": "S9.4"}], E2E, None)
    assert any("S9 is not a source key" in p for p in probs)


def test_inline_sentence_id_lists_and_bare_markers_count_as_their_sources():
    g = docketgen.collapse_sentence_cites({"t": "Both apply [S1.18, S2.3] and [S1.4; S1.6-S1.7].",
                                           "cites": ["S1.18", "S1", "S2.3-S2.4"],
                                           "checks": [{"claim": "x [S1.2]", "sentence": "S1.2", "cites": ["S1.2"]}]})
    assert g["t"] == "Both apply [S1][S2] and [S1]."
    assert g["cites"] == ["S1", "S2"]
    assert g["checks"][0] == {"claim": "x [S1]", "sentence": "S1.2", "cites": ["S1.2"]}
    assert [m.group(1) for m in docketgen._CITE.finditer("a [S1.18] b [S2 p.4] c [S3.2-S3.4]")] == ["S1", "S2", "S3"]
    assert docket_adapter._keys_in("x [S1.18] y") == ["S1"]


def test_cite_key_normalises_sentence_ids_and_keeps_everything_else():
    k = docketgen._cite_key
    assert [k("S1.18"), k("[S1.18]"), k("S1.18-S1.20"), k("S1.18-20"), k("S1.18 – S1.20"), k("S1 p.3"), k("S2")] == \
           ["S1"] * 6 + ["S2"]
    assert k("S1.4-S2.5") not in E2E and k("S1.x") not in E2E and k("S9.4") == "S9"
    assert grounding._key("S1.18") == "S1" and grounding._key("[S1.2-S1.3]") == "S1"


def test_writer_prompt_says_which_field_takes_sentence_ids_and_which_takes_source_ids():
    task = docketgen.writer_task("week 2", "A")
    assert '"cites"' in task and "SOURCE id" in task and "SENTENCE id" in task
    assert 'never\n  ["S1.47"]' in task or 'never ["S1.47"]' in task
    assert 'ONLY in a check\'s "sentence" field' in task
    assert docketgen.PROMPT_VERSION == "writer-v2.2"
