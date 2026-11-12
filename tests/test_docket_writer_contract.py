"""writer-v2.4: both repairs restate the writer contract, a round without a usable "kind" takes its planned kind,
a repair that makes the draft worse is not fed to the targeted repair, and a failed draft keeps its per-stage
problems. Synthetic fixtures and a mocked Coder only."""
import json

import docketgen
from test_docketgen_v2 import KEYED, _fake, _run, inter


def _collapsed():
    """Every round written without its planned shape: the slot and spot rounds lost their "kind" and fields."""
    g = inter("A")
    g["rounds"][1] = {"topic": "Custom", "question": "Map each fact.", "options": [], "cites": ["S1"]}
    g["rounds"][2] = {"topic": "Issues", "question": "Highlight.", "cites": ["S1"]}
    return g


def _one_slip():
    """A draft with one small slip: two wrong options share their teaching."""
    g = inter("A")
    g["rounds"][0]["options"][2]["teaching"] = g["rounds"][0]["options"][3]["teaching"]
    return g


def _fail(replies, **kw):
    try:
        _run(replies, [], **kw)
    except docketgen.ChecksFailed as e:
        return e
    raise AssertionError("expected ChecksFailed")


def _log_of_failed_run(replies):
    """The calls a run makes before it fails (the shared _run only returns its log on success)."""
    log = []
    prefix = "PREFIX\n\n" + docketgen.ranked_sources_block(KEYED, "", None)
    try:
        docketgen.write_draft_v2(_fake(list(replies), log), system="BRIEF", prefix=prefix, label="week 2", mix="A",
                                 keyed=KEYED)
    except docketgen.ChecksFailed:
        return log
    raise AssertionError("expected ChecksFailed")


def test_both_repairs_restate_the_plan_shapes_option_rule_and_id_rules():
    log = _log_of_failed_run([_collapsed(), _collapsed(), _collapsed()])
    assert [r for _, r, _, _ in log] == ["write", "repair", "repair_targeted"]
    for _, role, _, task in log[1:]:
        assert "THE WRITER CONTRACT" in task, role
        assert "round 1: mcq, round 2: slot, round 3: spot" in task
        assert '"kind": "slot"' in task and '"kind": "spot"' in task and '"elements"' in task and '"issues"' in task
        assert '"kind": "order"' not in task                       # only the shapes of this mix
        assert "exactly four options, keys A, B, C and D" in task
        assert "SENTENCE id (S1.47) goes ONLY in a check's \"sentence\" field" in task
        assert "never a claim, a paraphrase or a quote" in task and "Do NOT type quotes" in task
        marker = "YOUR GAME:\n" if role == "repair_targeted" else "LAST ATTEMPT:\n"
        assert task.index("THE WRITER CONTRACT") < task.index(marker)      # contract before the game JSON
    assert "TASK (targeted repair)" in log[2][3] and "Fix ONLY these problems" in log[2][3]
    assert "returning the game unchanged fails again" in log[2][3]


def test_repair_prompts_without_a_mix_are_unchanged_for_old_callers():
    assert "WRITER CONTRACT" not in docketgen.repair_task(["x"], "{}")
    assert "WRITER CONTRACT" not in docketgen.targeted_repair_task(["x"], "{}")
    assert "WRITER CONTRACT" in docketgen.repair_task(["x"], "{}", "B") and "round 3: order" in \
        docketgen.repair_task(["x"], "{}", "B")


def test_writer_task_carries_the_contract_and_the_label_rule():
    t = docketgen.writer_task("week 2", "A")
    assert docketgen.contract_rules("A") in t
    assert "keeping every qualifier and threshold word" in t and "never repeats the\nname of the element" in t
    assert '"elements": ["Element one"' not in t and '"label": "Issue name"' not in t
    assert docketgen.PROMPT_VERSION == "writer-v2.4"


def test_a_round_without_kind_takes_its_planned_kind_and_says_so():
    g = inter("A")
    del g["rounds"][1]["kind"]
    g["rounds"][2]["kind"] = "highlight"                           # renamed: not a kind the player knows
    game, probs = docketgen.compile_game(g, "A")
    assert probs[0].startswith('Round 2 has no "kind"') and '"kind": "slot"' in probs[0]
    assert probs[1].startswith('Round 3 has an unknown "kind"') and '"kind": "spot"' in probs[1]
    assert not any(p.startswith("The round plan is") for p in probs)
    kinds = [s["quiz"].get("kind", "mcq") for s in game["scenes"] if s.get("quiz")]
    assert kinds == ["mcq", "slot", "spot"]                        # compiled as planned: no mcq cascade
    bad = docketgen.validate_v2(game, KEYED.keys(), "A")
    assert not any("four options" in b or "exactly one correct" in b for b in bad)


def test_a_wrong_kind_is_named_per_round():
    g = inter("A")
    g["rounds"][1]["kind"] = "mcq"
    _, probs = docketgen.compile_game(g, "A")
    assert "The round plan is mcq, slot, spot; you wrote mcq, mcq, spot." in probs
    assert "Round 2 must be a slot round, in the slot shape, not mcq." in probs


def test_a_round_that_is_not_an_object_does_not_crash_the_compiler():
    g = inter("A")
    g["rounds"][2] = "spot round here"
    game, probs = docketgen.compile_game(g, "A")
    assert game is not None and probs and probs[0].startswith('Round 3 has no "kind"')


def test_a_repair_that_makes_the_draft_worse_is_not_fed_to_the_targeted_repair():
    fixed = inter("A"); fixed["title"] = "Fixed"
    out, log = _run([_one_slip(), _collapsed(), fixed], [{"verdict": "ok", "issues": []}])
    assert [r for _, r, _, _ in log] == ["write", "repair", "repair_targeted", "review"]
    sent = json.loads(log[2][3].split("YOUR GAME:\n", 1)[1])
    assert sent["rounds"] == _one_slip()["rounds"]                 # the first draft, not the collapsed repair
    assert "options C, D" in log[2][3]                             # and the first draft's own problem
    assert out["repaired"] is True and out["game"]["title"] == "Fixed"


def test_a_repair_that_does_not_parse_falls_back_to_the_first_draft():
    out, log = _run([_one_slip(), "not json", inter("A")], [{"verdict": "ok", "issues": []}])
    assert [r for _, r, _, _ in log] == ["write", "repair", "repair_targeted", "review"]
    assert json.loads(log[2][3].split("YOUR GAME:\n", 1)[1])["rounds"] == _one_slip()["rounds"]
    assert out["repaired"] is True


def test_a_better_repair_is_kept():
    fixed = inter("A")
    worse = _collapsed()
    out, log = _run([worse, _one_slip(), fixed], [{"verdict": "ok", "issues": []}])
    assert json.loads(log[2][3].split("YOUR GAME:\n", 1)[1])["rounds"] == _one_slip()["rounds"]


def test_a_failed_draft_keeps_every_stage_problem_list():
    e = _fail([_collapsed(), _collapsed(), _collapsed()])
    assert [s["stage"] for s in e.stages] == ["write", "repair", "repair_targeted"]
    assert all(s["problems"] for s in e.stages)
    assert len(e.stages[0]["problems"]) > 4                        # the message keeps four; the stages keep all
    assert str(e).startswith("The game did not pass the checks: ")
    e = _fail([_one_slip(), _one_slip(), "not json"])
    assert e.stages[-1] == {"stage": "repair_targeted", "problems": ["The writer did not return a JSON object."]}


def test_duplicate_teaching_names_the_options():
    game, _ = docketgen.compile_game(_one_slip(), "A")
    bad = docketgen.validate_v2(game, KEYED.keys(), "A")
    assert any("several options share the same teaching text (options C, D)" in b for b in bad)
