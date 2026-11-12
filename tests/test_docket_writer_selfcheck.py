"""writer-v2.5: the writer contract (and so both repair prompts) requires a full IRAC verdict and at least one quoted
check per round; one bounded legal self-check pass runs after the writer checks pass and before the review (and so
before best-of-N's doctrine judge). Synthetic fixtures and a mocked Coder only."""
import json

import docketgen
from test_docketgen_v2 import KEYED, _run, inter


def _sc(reply):
    """A queued self-check reply for test_docketgen_v2._fake."""
    return {"_selfcheck": reply}


def _no_irac():
    g = inter("A")
    g["verdict"]["irac"] = []
    return g


def _two_checks():
    g = inter("A")
    g["checks"] = g["checks"][:2]
    return g


def _fail(replies, **kw):
    try:
        _run(replies, [], **kw)
    except docketgen.ChecksFailed as e:
        return e
    raise AssertionError("expected ChecksFailed")


def test_contract_requires_a_full_irac_and_one_check_per_round():
    rules = docketgen.contract_rules("A")
    assert '"irac" list with at least one entry' in rules and '"application" and "conclusion"' in rules
    assert '"checks" has at least 3 entries' in rules and "at least one check for EVERY round" in rules
    assert docketgen.PROMPT_VERSION == "writer-v2.5"


def test_both_repair_prompts_restate_the_irac_and_check_rules_with_their_shapes():
    for task in (docketgen.repair_task(["p"], "{}", "A"), docketgen.targeted_repair_task(["p"], "{}", "A")):
        assert '"irac" list with at least one entry' in task and "at least one check for EVERY round" in task
        assert '"irac": [{"issue": "...", "rule": "... [KEY]"' in task
        assert '"checks": [{"claim": "a legal claim the game relies on", "sentence": "S1.47"}]' in task


def test_an_incomplete_irac_entry_fails_the_checks():
    g = inter("A")
    g["verdict"]["irac"] = [{"issue": "the issue", "rule": "the rule [S1]", "application": "", "conclusion": ""}]
    game = docketgen.compile_game(g, "A")[0]
    game["checks"], _ = docketgen.numbered_sentence_checks(game["checks"], KEYED)
    bad = docketgen.validate_v2(game, KEYED.keys(), "A")
    assert any("IRAC entry 1 has no application, conclusion" in p for p in bad)
    assert not docketgen.validate_v2(docketgen.compile_game(inter("A"), "A")[0], KEYED.keys(), "A")


def test_unresolved_checks_do_not_count_towards_one_per_round():
    game = docketgen.compile_game(inter("A"), "A")[0]
    game["checks"][2] = {**game["checks"][2], "unresolved": True}
    assert any("2 checks for 3 rounds" in p for p in docketgen.validate_v2(game, KEYED.keys(), "A"))


def test_a_draft_with_no_irac_is_repaired_with_the_rule_in_the_prompt():
    out, log = _run([_no_irac(), inter("A")], [{"verdict": "ok", "issues": []}])
    assert [r for _, r, _, _ in log] == ["write", "repair", "selfcheck", "review"]
    assert "The verdict has no IRAC." in log[1][3] and '"irac" list with at least one entry' in log[1][3]


def test_too_few_checks_reach_the_targeted_repair_with_the_rule():
    e = _fail([_two_checks(), _two_checks(), _two_checks()])
    assert "2 checks for 3 rounds" in str(e)
    assert [s["stage"] for s in e.stages] == ["write", "repair", "repair_targeted"]


def test_selfcheck_runs_once_between_the_checks_and_the_review_and_its_fix_is_kept():
    fixed = inter("A")
    fixed["rounds"][1]["elements"] = ["General and consistent state practice", "Opinio juris"]
    for f in fixed["rounds"][1]["facts"]:
        if f["element"] == "State practice":
            f["element"] = "General and consistent state practice"
    out, log = _run([inter("A"), _sc(fixed)], [{"verdict": "ok", "issues": []}])
    assert [(t, r) for t, r, _, _ in log] == [("coder", "write"), ("coder", "selfcheck"), ("thinker", "review")]
    task = log[1][3]
    assert task.startswith("PREFIX\n\n") and "TASK (legal self-check)" in task
    assert "CHECKED SENTENCES:" in task and "State practice must be general and consistent" in task  # code-copied
    assert "Keep every wrong mcq option wrong on purpose" in task and "THE WRITER CONTRACT" in task
    assert json.loads(task.split("YOUR GAME:\n", 1)[1]) == inter("A")
    assert out["selfchecked"] is True and out["intermediate"] == fixed
    assert "General and consistent state practice" in json.dumps(out["game"])
    assert "General and consistent state practice" in log[2][3]          # the reviewer sees the fixed game
    assert [c["role"] for c in out["calls"]] == ["write", "selfcheck", "review"]


def test_selfcheck_unchanged_or_unparseable_keeps_the_draft():
    for reply in (inter("A"), "not json at all"):
        out, log = _run([inter("A"), _sc(reply)], None)
        assert [r for _, r, _, _ in log] == ["write", "selfcheck"]
        assert out["selfchecked"] is False and out["intermediate"] == inter("A")


def test_selfcheck_that_breaks_a_writer_check_is_discarded_without_a_second_try():
    broken = inter("A"); broken["title"] = "Broken"; broken["rounds"] = broken["rounds"][:2]
    out, log = _run([inter("A"), _sc(broken)], [{"verdict": "ok", "issues": []}])
    assert [r for _, r, _, _ in log] == ["write", "selfcheck", "review"]      # one pass only
    assert out["selfchecked"] is False and out["game"]["title"] != "Broken"


def test_selfcheck_that_adds_an_off_source_citation_is_discarded():
    worse = inter("A"); worse["title"] = "Invented"
    gone = lambda game: ["an invented authority"] if game.get("title") == "Invented" else []  # noqa: E731
    out, _ = _run([inter("A"), _sc(worse)], None, unverified=gone)
    assert out["selfchecked"] is False and out["unverified"] == [] and out["game"]["title"] != "Invented"


def test_no_selfcheck_when_the_checks_fail():
    e = _fail([_no_irac(), _no_irac(), _no_irac()])
    assert "selfcheck" not in [c["role"] for c in e.calls]


def test_selfcheck_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("CF_DOCKET_SELFCHECK", "0")
    out, log = _run([inter("A")], None)
    assert [r for _, r, _, _ in log] == ["write"] and out["selfchecked"] is False
