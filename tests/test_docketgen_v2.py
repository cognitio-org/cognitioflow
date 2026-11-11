"""WRITER v2 (Game Studio model-quality plan rungs 0-2): the pure pieces in docketgen. Synthetic fixtures only."""
import copy
import json

import docketgen
import relevance

SRC = ("A reservation is a unilateral statement made by a State when signing a treaty. "
       "Opinio juris is the belief that a practice is legally required. State practice must be general and consistent.")
KEYED = {"S1": {"name": "wk2.txt", "role": "lecture", "text": SRC}}


def inter(mix="A"):
    mcq = {"kind": "mcq", "topic": "Reservations", "set": "courtroom", "dialogue": [{"speaker": "JUDGE VOS", "line": "Well?"}],
           "question": "Ruritania signed with a statement excluding one clause. What is it?",
           "options": [{"key": "A", "text": "A reservation", "correct": True, "teaching": "It is a unilateral statement [S1]"},
                       {"key": "B", "text": "A treaty amendment", "correct": False, "flaw": "confuses a unilateral act with an agreed one",
                        "mistake": "Amendment confusion", "teaching": "An amendment needs the parties' agreement [S1]"},
                       {"key": "C", "text": "Customary law", "correct": False, "flaw": "mixes up sources",
                        "mistake": "Wrong source", "teaching": "Custom needs state practice and opinio juris [S1]"},
                       {"key": "D", "text": "Nothing", "correct": False, "flaw": "ignores the statement",
                        "mistake": "Ignoring the act", "teaching": "The statement has legal effect [S1]"}],
           "cites": ["S1"]}
    slot = {"kind": "slot", "topic": "Custom", "question": "Map each fact.", "elements": ["State practice", "Opinio juris"],
            "facts": [{"fact": "Ten states did X", "element": "State practice"},
                      {"fact": "They said X was required", "element": "Opinio juris"},
                      {"fact": "For fifty years", "element": "State practice"}],
            "teaching": "Practice and belief [S1]", "cites": ["S1"]}
    spot = {"kind": "spot", "topic": "Issues", "question": "Highlight.",
            "text": "Ruritania signed the treaty with a statement. Its neighbours protested for years.",
            "issues": [{"label": "Reservation", "phrase": "signed the treaty with a statement"},
                       {"label": "Objection", "phrase": "neighbours protested"}],
            "teaching": "Reservations and objections [S1]", "cites": ["S1"]}
    order = {"kind": "order", "topic": "Custom test", "question": "Order the steps.",
             "steps": ["identify state practice", "check opinio juris", "conclude on custom"],
             "teaching": "First identify state practice, then check opinio juris, then conclude on custom [S1]", "cites": ["S1"]}
    by = {"mcq": mcq, "slot": slot, "spot": spot, "order": order}
    rounds = [copy.deepcopy(by[k]) for k in docketgen.MIXES[mix]]
    for i, r in enumerate(rounds):
        if r["kind"] == "mcq" and i:
            for o in r["options"]:
                o["teaching"] += f" (round {i})"
    return {"title": "The Ruritanian Statement", "logline": "l", "learning_goal": "g", "case_file": ["Claimant: X"],
            "arrival": {"place": "Harbour", "action": ["walk"], "dialogue": []}, "rounds": rounds,
            "verdict": {"outcome": "WON", "irac": [{"issue": "i", "rule": "the rule [S1]", "application": "a", "conclusion": "c"}],
                        "takeaway": "t"},
            "epilogue": {"action": ["e"]},
            "checks": [{"claim": "reservations are unilateral", "cites": ["S1"],
                        "quote": "A reservation is a unilateral statement made by a State"}]}


def test_every_mix_clears_the_generation_ratio_and_the_banned_one_does_not():
    for mix in docketgen.MIXES:
        game, probs = docketgen.compile_game(inter(mix), mix)
        assert probs == [], (mix, probs)
        assert docketgen.validate_v2(game, KEYED.keys(), mix) == [], mix
        assert docketgen.generation_ratio(game) >= docketgen.MIN_GEN_RATIO
    banned = inter("C")
    banned["rounds"] = [inter("C")["rounds"][0], inter("C")["rounds"][1], inter("B")["rounds"][2]]   # 2 mcq + order
    game, _ = docketgen.compile_game(banned)
    assert any("produced" in p for p in docketgen.validate_v2(game, KEYED.keys()))


def test_code_picks_the_mix_deterministically_and_spreads_it():
    assert docketgen.pick_mix("g1") == docketgen.pick_mix("g1")
    assert {docketgen.pick_mix(f"g{i}") for i in range(40)} == set(docketgen.MIXES)
    task = docketgen.writer_task("week 2", "B")
    assert "round 1: mcq, round 2: slot, round 3: order" in task
    assert '"kind": "spot"' not in task and '"kind": "order"' in task and '"flaw"' in task and '"quote"' in task


def test_writing_off_the_plan_is_rejected():
    game, probs = docketgen.compile_game(inter("A"), "B")
    assert any("round plan" in p for p in probs)
    assert any("round plan" in p for p in docketgen.validate_v2(game, KEYED.keys(), "B"))


def test_compiler_computes_spot_offsets_ids_and_keys():
    game, _ = docketgen.compile_game(inter("A"), "A")
    spot = game["scenes"][3]["quiz"]
    for it in spot["answer"]["issues"]:
        a, b = it["spans"][0]
        assert spot["text"][a:b] in ("signed the treaty with a statement", "neighbours protested")
    slot = game["scenes"][2]["quiz"]["answer"]
    assert slot["key"] == {"f1": "e1", "f2": "e2", "f3": "e1"}
    opts = game["scenes"][1]["quiz"]["options"]
    assert opts[1]["flaw"] and opts[1]["outcome_title"] == "Amendment confusion" and opts[0]["flaw"] == ""
    assert docketgen.validate(docketgen.finish(game, "g", "CF-x", KEYED), KEYED.keys()) == []


def test_bad_spot_phrase_and_unknown_slot_element_go_to_repair():
    g = inter("A")
    g["rounds"][2]["issues"][0]["phrase"] = "a phrase the text does not contain"
    g["rounds"][1]["facts"][0]["element"] = "Nonsense"
    _, probs = docketgen.compile_game(g, "A")
    assert any("not an exact phrase" in p for p in probs) and any("not one of its elements" in p for p in probs)


def test_v2_rules_flaw_distinct_teaching_order_teaching_and_quotes():
    g = inter("B")
    g["rounds"][0]["options"][1]["flaw"] = ""
    g["rounds"][0]["options"][2]["teaching"] = g["rounds"][0]["options"][3]["teaching"]
    g["rounds"][2]["teaching"] = "To conclude on custom you must check opinio juris; but first identify state practice"
    g["checks"][0]["quote"] = ""
    game, _ = docketgen.compile_game(g, "B")
    bad = docketgen.validate_v2(game, KEYED.keys(), "B")
    assert any("states no flaw" in p for p in bad)
    assert any("same teaching" in p for p in bad)
    assert any("different order" in p for p in bad)
    assert any("no quote" in p for p in bad)


def test_tolerant_json_parse():
    assert docketgen.parse_json_tolerant('```json\n{"a": [1, 2,], "b": {"c": 1,},}\n```') == {"a": [1, 2], "b": {"c": 1}}
    assert docketgen.parse_json_tolerant('Here it is: {"a": 1} hope that helps') == {"a": 1}
    assert docketgen.parse_json_tolerant("no json") is None and docketgen.parse_json_tolerant("[1, 2]") is None


def test_dedupe_keeps_checked_else_newest():
    files = [{"id": 1, "name": "Week 2 worksheet.pdf", "created": 1}, {"id": 2, "name": "lecture.txt", "created": 1},
             {"id": 3, "name": "Week 2 worksheet (1).pdf", "created": 5}, {"id": 4, "name": "Week-2 worksheet checked.pdf", "created": 2}]
    assert [f["id"] for f in docketgen.dedupe_versions(files)] == [4, 2]
    assert [f["id"] for f in docketgen.dedupe_versions(files[:3])] == [3, 2]


def test_ranked_sources_keep_relevant_verbatim_passages_and_keys():
    filler = "\n\n".join(f"Paragraph {i} about tax and farming subsidies." * 20 for i in range(60))
    key = "Opinio juris is the belief that a practice is legally required."
    big = filler + "\n\n" + key + "\n\n" + filler   # the relevant passage sits past the first FILE_CHARS
    keyed = {"S1": {"name": "reader.txt", "text": big}, "S2": {"name": "wg.txt", "text": "short WG"}}
    block = docketgen.ranked_sources_block(keyed, "opinio juris belief legally required practice", relevance.rank)
    assert key in block and 'key="S1"' in block and 'key="S2"' in block and "[…]" in block
    assert block.count("Paragraph") < big.count("Paragraph")
    assert docketgen.ranked_sources_block(keyed, "", relevance.rank) == docketgen.sources_block(keyed)


def _fake(replies, log, role_tag="coder"):
    def fn(role, system, user, max_tokens):
        log.append((role_tag, role, system, user))
        r = replies.pop(0)
        return (r if isinstance(r, str) else json.dumps(r)), f"mlx-community/Qwen3-{role_tag}", "http://127.0.0.1:8080/v1"
    return fn


def _run(coder_replies, reviewer_replies=None, **kw):
    log = []
    rev = _fake(list(reviewer_replies), log, "thinker") if reviewer_replies is not None else None
    out = docketgen.write_draft_v2(_fake(list(coder_replies), log), system="BRIEF", prefix="PREFIX", label="week 2",
                                   mix="A", keyed=KEYED, reviewer=rev, **kw)
    return out, log


def test_pipeline_write_review_ok_shares_prefix_and_records_every_call():
    out, log = _run([inter("A")], [{"verdict": "ok", "issues": []}])
    assert [(t, r) for t, r, _, _ in log] == [("coder", "write"), ("thinker", "review")]
    assert all(s == "BRIEF" and u.startswith("PREFIX\n\n") for _, _, s, u in log)
    assert log[0][3].rstrip().endswith("1 to 3 checks per round.") and "TASK (reviewer)" in log[1][3]
    assert "WRONG ON PURPOSE" in log[1][3] and "Do NOT suggest a fix" in log[1][3]
    assert [c["role"] for c in out["calls"]] == ["write", "review"] and out["mix"] == "A" and not out["revised"]
    assert out["model"] == "mlx-community/Qwen3-coder"


def test_pipeline_repairs_once_then_fails_honestly():
    bad = inter("A"); bad["rounds"] = bad["rounds"][:2]
    out, log = _run([bad, inter("A")], [{"verdict": "ok", "issues": []}])
    assert [r for _, r, _, _ in log] == ["write", "repair", "review"] and "round plan" in log[1][3]
    try:
        _run([bad, bad], [])
    except ValueError as e:
        assert "did not pass the checks" in str(e)
    else:
        raise AssertionError("a game that still fails after one repair must not become a draft")


def test_quote_problems_block_and_trigger_repair():
    calls = []
    qp = lambda checks, keyed: (calls.append(1) or ["check 1: the quote is not in S1"]) if len(calls) < 1 else []  # noqa: E731
    out, log = _run([inter("A"), inter("A")], None, quote_problems=qp)
    assert [r for _, r, _, _ in log] == ["write", "repair"] and "quote is not in S1" in log[1][3]
    try:
        _run([inter("A"), inter("A")], None, quote_problems=lambda c, k: ["check 1: not in S1"])
    except ValueError:
        pass
    else:
        raise AssertionError("unverifiable quotes after the repair round must fail the game")


def test_high_issue_is_revised_and_rereviewed_on_the_thinker_no_coder_self_review():
    fixed = inter("A"); fixed["title"] = "Corrected"
    out, log = _run([inter("A"), fixed],
                    [{"verdict": "fix", "issues": [{"where": "round 1 option B", "problem": "also right", "severity": "high",
                                                     "quote": "x", "fix": "say Y"}]},
                     {"verdict": "ok", "issues": []}])
    assert [(t, r) for t, r, _, _ in log] == [("coder", "write"), ("thinker", "review"), ("coder", "revise"), ("thinker", "review")]
    assert out["revised"] and out["game"]["title"] == "Corrected" and out["issues"] == []
    assert "fix" not in docketgen.review_issues_v2({"issues": [{"problem": "p", "fix": "f", "quote": "q"}]})[0]


def test_no_reviewer_means_no_review_call_and_no_coder_self_review():
    out, log = _run([inter("A")], None)
    assert [r for _, r, _, _ in log] == ["write"] and out["issues"] == []


def test_unverifiable_page_numbers_are_stripped():
    g = inter("A"); g["rounds"][0]["options"][0]["teaching"] = "It is a unilateral statement [S1 p.14]"
    out, _ = _run([g], None)
    assert out["game"]["scenes"][1]["quiz"]["options"][0]["teaching"].endswith("[S1]")
