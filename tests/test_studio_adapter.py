"""Studio adapter part 1 (S3): the pure projections from a finished docket game to gate inputs.
Wrong options are wrong on purpose: their text/story must never reach terminology or doctrine pass 1."""
import copy

import docketgen
from studio import docket_adapter as da
from test_docketgen import game
from test_produce_interactions import produce_game


def keyed():
    return docketgen.source_keys([
        {"id": "f1", "name": "Week 3 lecture.pdf", "role": "lecture", "text": "A contract made under duress is void."},
        {"id": "f2", "name": "WG notes.pdf", "role": "wg", "text": "State liability needs a sufficiently serious breach."},
    ])


def mcq_game():
    g = game()
    for s in g["scenes"]:
        for o in (s.get("quiz") or {}).get("options") or []:
            o["story"] = f"story {o['key']}"
    return g


def by_id(items):
    return {i["id"]: i for i in items}


def test_cited_source_text_dedupes_skips_unknown_and_caps():
    k = keyed()
    text = da.cited_source_text(["S1", "[S1 p.4]", "S9", "S2"], k)
    assert text.count("[S1] Week 3 lecture.pdf") == 1 and "[S2] WG notes.pdf" in text
    assert "void" in text and "sufficiently serious" in text and "S9" not in text
    assert da.cited_source_text([], k) == "" and da.cited_source_text(["S9"], k) == ""
    big = docketgen.source_keys([{"name": "a.pdf", "text": "A" * 20_000}, {"name": "b.pdf", "text": "B" * 20_000}])
    capped = da.cited_source_text(["S1", "S2"], big)
    assert len(capped) <= da.SOURCE_CAP and "[S2] b.pdf" in capped and "B" * 100 in capped


def test_terminology_items_exclude_wrong_options_text_and_story():
    items = by_id(da.items_for_terminology(mcq_game(), keyed()))
    assert list(items) == ["q2", "q3", "verdict"]
    q2 = items["q2"]
    assert q2["kind"] == "mcq" and q2["cites"] == ["S1"]
    assert "answer B" in q2["generated_text"]
    for wrong in ("answer A", "answer C", "answer D", "story A", "story C", "story D"):
        assert wrong not in q2["generated_text"]
    for k in "ABCD":
        assert f"because [S1] {k}" in q2["generated_text"]          # every option's teaching is checked
    assert "duress is void" in q2["source_text"] and "sufficiently serious" not in q2["source_text"]
    assert items["verdict"]["generated_text"] == "r [S1]" and items["verdict"]["cites"] == ["S1"]


def test_doctrine_rounds_carry_question_correct_answer_and_all_teaching():
    items = by_id(da.rounds_for_doctrine(mcq_game(), keyed()))
    assert list(items) == ["q2", "q3", "verdict"]
    gen = items["q3"]["generated_text"]
    assert "QUESTION: Advise her." in gen and "CORRECT ANSWER: answer B" in gen
    assert all(f"because [S1] {k}" in gen for k in "ABCD")
    assert not any(w in gen for w in ("answer A", "answer C", "answer D", "story A", "story C"))
    assert "IRAC RULE: r [S1]" in items["verdict"]["generated_text"]


def test_distractors_are_every_wrong_option_and_only_those():
    items = da.distractors_for_review(mcq_game(), keyed())
    assert [i["id"] for i in items] == ["q2:A", "q2:C", "q2:D", "q3:A", "q3:C", "q3:D"]
    a = items[0]
    assert a["round"] == "q2" and a["key"] == "A" and a["question"] == "Advise her."
    assert "OPTION: answer A" in a["generated_text"] and "STORY: story A" in a["generated_text"]
    assert "TEACHING: because [S1] A" in a["generated_text"] and "duress is void" in a["source_text"]
    assert not any("answer B" in i["generated_text"] for i in items)


def test_projections_work_on_the_finished_game_and_never_mutate_it():
    final = docketgen.finish(mcq_game(), "gabc", "CF-prop", keyed())
    before = copy.deepcopy(final)
    for fn in (da.items_for_terminology, da.rounds_for_doctrine, da.distractors_for_review):
        assert fn(final, keyed())
    assert final == before


def test_an_item_that_cites_nothing_is_checked_against_all_sources():
    g = mcq_game()
    for o in g["scenes"][1]["quiz"]["options"]:
        o["cites"], o["teaching"] = [], f"plain {o['key']}"
    q2 = by_id(da.items_for_terminology(g, keyed()))["q2"]
    assert q2["cites"] == [] and "[S1]" in q2["source_text"] and "[S2]" in q2["source_text"]


def test_produce_kinds_project_only_the_answer_key():
    g = produce_game()
    g["scenes"][2]["quiz"]["answer"]["bank"].append({"id": "e9", "label": "Direct effect first"})   # bank distractor
    g["scenes"][3]["quiz"]["answer"]["elements"].append({"id": "e4", "label": "Unused element"})
    items = by_id(da.items_for_terminology(g, keyed()))
    assert list(items) == ["q1", "q2", "q3", "verdict"]
    spot = items["q1"]["generated_text"]
    assert "State liability" in spot and "Causal link" in spot and "Two issues" in spot
    assert "Proportionality" not in spot                                   # taxonomy distractor
    order = items["q2"]["generated_text"]
    assert "1. The rule confers rights" in order and "3. Causal link to the loss" in order
    assert "Direct effect first" not in order
    slot = items["q3"]["generated_text"]
    assert "The directive conferred an individual right -> Rights" in slot and "Unused element" not in slot
    assert items["q1"]["kind"] == "spot" and items["q1"]["cites"] == ["S1"]
    doc = by_id(da.rounds_for_doctrine(g, keyed()))
    assert "FACTS: The Member State failed to transpose" in doc["q1"]["generated_text"]
    assert "CORRECT ANSWER: 2. The breach is sufficiently serious" in doc["q2"]["generated_text"]
    assert "Proportionality" not in doc["q1"]["generated_text"]
    assert da.distractors_for_review(g, keyed()) == []


def test_malformed_games_project_to_nothing_instead_of_raising():
    for bad in ({}, {"scenes": None}, {"scenes": ["x", {"quiz": "nope"}]}, {"verdict": "x"}):
        assert da.items_for_terminology(bad, keyed()) == []
        assert da.rounds_for_doctrine(bad, keyed()) == []
        assert da.distractors_for_review(bad, keyed()) == []


def test_distractor_items_carry_option_text_and_teaching_separately():
    """S4 #24: review_distractor takes the option (OPTION + STORY lines) and the teaching separately."""
    items = da.distractors_for_review(mcq_game(), keyed())
    a = items[0]
    assert a["option_text"] == "OPTION: answer A\nSTORY: story A"
    assert a["teaching"] == "because [S1] A"
    assert a["generated_text"] == "OPTION: answer A\nSTORY: story A\nTEACHING: because [S1] A"   # S3 shape unchanged


# ==================================================================================== S4: gate_docket(...)
# Fakes only: no network, no browser, no M4. Brief: ~/reports/cf-studio-s4-brief.md section 8 (tests 1-31),
# plus the owner decisions (unwired gates advisory, lexicon alias table) as tests D1-D5.
import json

import pytest

SRC = ("A contract made under duress is void. State liability needs a sufficiently serious breach "
       "and a direct causal link to the loss.")
QUOTE = "State liability needs a sufficiently serious breach"
COURSE = {"id": "eu", "slug": "eu", "name": "EU law"}
SENTINEL = "SENTINEL-REASONING-7f3a"


@pytest.fixture(autouse=True)
def _no_studio_env(monkeypatch):
    """A developer shell pointing CF_STUDIO_* at the real M4 must never reach these tests."""
    import os
    for k in list(os.environ):
        if k.startswith("CF_STUDIO_"):
            monkeypatch.delenv(k, raising=False)


def rtmod():
    """studio.runtime exactly as the adapter's loader sees it (same exception classes)."""
    return da._gates().runtime


def ok_reply(*quotes):
    return json.dumps({"ok": True, "issues": [], "quotes": list(quotes or [QUOTE])})


def bad_reply(issue="unsupported"):
    return json.dumps({"ok": False, "issues": [issue], "quotes": []})


class FakeReviewer:
    """script: None (always ok + verbatim quote), a callable (n, prompt) -> reply, or a list (one per call).
    A reply that is an exception instance is raised."""
    model = "fake-reviewer"

    def __init__(self, script=None):
        self.script, self.prompts = script, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        n = len(self.prompts) - 1
        if self.script is None:
            r = ok_reply()
        elif callable(self.script):
            r = self.script(n, prompt)
        else:
            r = self.script[min(n, len(self.script) - 1)]
        if isinstance(r, BaseException):
            raise r
        return r


class CleanPage:
    def console_errors(self):
        return []

    def query(self, selector):
        return True

    def title(self):
        return "The Harbour Permit"


class BrokenPage(CleanPage):
    def console_errors(self):
        return ["TypeError: x is undefined"]


class CleanA11y:
    def focus_visible(self):
        return True

    def reduced_motion_respected(self):
        return True

    def min_tap_target_px(self):
        return 44.0

    def min_contrast_ratio(self):
        return 7.0


def vlm_ok(path):
    return '{"score": 0.9, "notes": "clean"}'


def full_runtime(**over):
    rt = {"reviewer": FakeReviewer(), "page_probe": CleanPage(), "a11y_probe": CleanA11y(),
          "screenshot": "shot.png", "vlm": vlm_ok}
    rt.update(over)
    return rt


def src_keyed(text=SRC, *more):
    files = [{"id": "f1", "name": "Week 3 lecture.pdf", "role": "lecture", "text": text}]
    files += [{"id": f"f{i}", "name": f"extra{i}.pdf", "role": "law", "text": t} for i, t in enumerate(more, 2)]
    return docketgen.source_keys(files)


def mcq_round(n, cites=("S1",)):
    return {"id": f"s{n}", "title": "Pick", "phase": "examination", "set": "courtroom", "action": ["x"],
            "dialogue": [], "quiz": {"id": f"q{n}", "question": "Advise her.", "options": [
                {"key": k, "text": f"answer {k}", "correct": k == "B", "teaching": f"because {k} [S1]",
                 "cites": list(cites)} for k in "ABCD"]}}


def mixed_game():
    """produce_game() + one mcq round: retrieval passes (an mcq-only game has generation ratio 0)."""
    g = produce_game()
    g["scenes"].insert(4, mcq_round(4))
    return g


def finished(g=None, keyed_=None):
    return docketgen.finish(g if g is not None else mixed_game(), "gabc", "CF-eu", keyed_ or src_keyed())


def run(final=None, keyed_=None, *, course=COURSE, issues=(), unverified=(), mode="shadow", heartbeat=None,
        runtime=None, texts=("t",)):
    keyed_ = keyed_ or src_keyed()
    return da.gate_docket(final if final is not None else finished(keyed_=keyed_), keyed_, list(texts), course,
                          issues=list(issues) if isinstance(issues, tuple) else issues,
                          unverified=list(unverified) if isinstance(unverified, tuple) else unverified,
                          mode=mode, heartbeat=heartbeat,
                          runtime=full_runtime() if runtime is None else runtime)


def gate(card, name):
    return next(g for g in card["gates"] if g["name"] == name)


CARD_TYPES = {"schema": str, "game": dict, "overall_pass": bool, "gates": list, "blocking_failures": list,
              "mode": str, "infra_error": bool, "enforced": list, "not_wired": list, "config_warning": str,
              "lexicon_version": str, "lexicon_status": str, "engine_hash": str, "game_sha256": str,
              "reviewer_model": str, "reviewer_calls": int, "heartbeat_errors": int, "budget_exhausted": bool,
              "timings_ms": dict, "doctrine_items": list, "texts_count": int, "truncated": bool}


def assert_schema(card):
    assert isinstance(card, dict)
    for key, typ in CARD_TYPES.items():
        assert isinstance(card.get(key), typ), (key, card.get(key))
    assert card["schema"] == "studio-card/1" and card["mode"] in ("shadow", "enforce")
    assert set(card["game"]) == {"title", "course", "gid"}
    for g in card["gates"]:
        assert isinstance(g["name"], str) and isinstance(g["passed"], bool) and isinstance(g["mandatory"], bool)
        assert isinstance(g["designed_mandatory"], bool) and isinstance(g["detail"], str)
    assert all(isinstance(n, str) for n in card["blocking_failures"])
    assert all(isinstance(v, int) for v in card["timings_ms"].values())
    for it in card["doctrine_items"]:
        assert set(it) == {"id", "pass", "ok", "issues", "quotes_ok", "source_chars", "keys_windowed", "uncited",
                           "infra"}
        assert len(it["issues"]) <= 3 and all(len(s) <= 200 for s in it["issues"])
    assert json.loads(json.dumps(card, allow_nan=False)) == card                                     # 19
    assert len(json.dumps(card, ensure_ascii=False).encode("utf-8")) <= da.CARD_MAX_BYTES
    return card


# ------------------------------------------------------------------------------------------- 1. all pass

def test_01_all_pass_fakes_pass_the_card():
    card = assert_schema(run())
    assert card["overall_pass"] is True and card["blocking_failures"] == [] and card["infra_error"] is False
    assert all(g["passed"] for g in card["gates"]), [(g["name"], g["detail"]) for g in card["gates"]]
    assert card["enforced"] == list(da.DESIGN_MANDATORY) and card["not_wired"] == []
    assert gate(card, "polish")["mandatory"] is False and gate(card, "polish")["designed_mandatory"] is False
    assert card["lexicon_version"] == "eu-law-draft-1" and card["reviewer_model"] == "fake-reviewer"
    assert len(card["engine_hash"]) == 64 and len(card["game_sha256"]) == 64 and card["texts_count"] == 1
    assert card["config_warning"] == "" and card["truncated"] is False
    assert set(card["timings_ms"]) == set(da.GATE_ORDER) | {"total"}
    assert da.block_message(card).startswith(docketgen.GATE_BLOCKED)        # only called on failure, still safe


# --------------------------------------------------------------------- 2. an exception in each gate, both modes

@pytest.mark.parametrize("mode", ["shadow", "enforce"])
@pytest.mark.parametrize("name", da.GATE_ORDER)
def test_02_an_exception_in_any_gate_fails_only_that_gate(monkeypatch, name, mode):
    baseline = {g["name"]: g["passed"] for g in run()["gates"]}

    def boom(ctx):
        raise RuntimeError(f"injected into {name}")

    monkeypatch.setattr(da, f"_g_{name}", boom)
    card = assert_schema(run(mode=mode))
    assert card["mode"] == mode
    g = gate(card, name)
    assert g["passed"] is False and "injected" in g["detail"] and "fail-closed" in g["detail"]
    assert {n: p for n, p in ((x["name"], x["passed"]) for x in card["gates"]) if n != name} == \
        {n: p for n, p in baseline.items() if n != name}
    assert card["infra_error"] is False
    if name != "polish":
        assert card["overall_pass"] is False and card["blocking_failures"] == [name]
    else:
        assert card["overall_pass"] is True                                  # advisory: never blocks


# ------------------------------------------------------------------------- 3. timeout-only -> gates unavailable

def test_03_reviewer_timeouts_only_make_the_card_infra():
    rt = rtmod()
    card = assert_schema(run(runtime=full_runtime(reviewer=FakeReviewer([rt.GateInfraError("timed out")]))))
    assert card["blocking_failures"] == ["doctrine"] and card["infra_error"] is True
    assert "GateInfraError" in gate(card, "doctrine")["infra"]
    msg = da.block_message(card)
    assert msg.startswith(docketgen.GATE_UNAVAILABLE) and "timed out" in msg


# ----------------------------------------------------------------------------------------------- 4. subset

def test_04_enforce_subset_lets_a_failing_unenforced_gate_through(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", " terminology , citations ")
    card = assert_schema(run(final=finished(game())))                       # mcq-only: retrieval fails
    r = gate(card, "retrieval")
    assert r["passed"] is False and r["mandatory"] is False and r["designed_mandatory"] is True
    assert card["enforced"] == ["terminology", "citations"]
    assert card["overall_pass"] is True and card["blocking_failures"] == []


# ------------------------------------------------------------------------------------------ 5. unknown token

def test_05_unknown_enforce_token_enforces_everything_and_warns(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", "terminolgy, citations")
    card = assert_schema(run(final=finished(game())))
    assert card["enforced"] == list(da.DESIGN_MANDATORY)
    assert "terminolgy" in card["config_warning"]
    assert card["overall_pass"] is False and "retrieval" in card["blocking_failures"]


# ---------------------------------------------------------------------------------------------- 6. heartbeat

def test_06_heartbeat_precedes_every_reviewer_call():
    beats, rev = [], FakeReviewer()
    card = assert_schema(run(heartbeat=lambda: beats.append(1), runtime=full_runtime(reviewer=rev)))
    assert card["reviewer_calls"] == len(rev.prompts) == 8                  # 4 rounds + verdict + 3 distractors
    assert len(beats) >= card["reviewer_calls"] + 1


# ---------------------------------------------------------------------------------------------- 7. 32 KB cap

def test_07_an_oversized_card_is_cut_under_32kb_with_core_keys_intact():
    g = game()
    g["scenes"] = [g["scenes"][0]] + [mcq_round(n) for n in range(2, 32)] + g["scenes"][3:]
    long_issue = "é" * 1000                                                 # 2 bytes each in UTF-8
    rev = FakeReviewer(lambda n, p: json.dumps({"ok": False, "issues": [long_issue] * 3, "quotes": []}))
    card = assert_schema(run(final=finished(g), issues=[{"where": "q2", "problem": "P" * 100_000,
                                                          "severity": "high"}],
                             runtime=full_runtime(reviewer=rev)))
    assert card["truncated"] is True
    assert len(json.dumps(card, ensure_ascii=False).encode("utf-8")) <= 32_768
    assert card["overall_pass"] is False and card["infra_error"] is False
    assert set(card["blocking_failures"]) == {"doctrine", "reviewer_high", "retrieval"}
    assert [x["name"] for x in card["gates"]] == list(da.GATE_ORDER)
    assert card["reviewer_calls"] == 31 + 90 and card.get("doctrine_items_dropped", 0) > 0


# ------------------------------------------------------------------------------------- 8. quote-less ok:true

def test_08_a_quoteless_ok_true_fails_doctrine():
    rev = FakeReviewer(lambda n, p: json.dumps({"ok": True, "issues": []}))
    card = assert_schema(run(runtime=full_runtime(reviewer=rev)))
    d = gate(card, "doctrine")
    assert d["passed"] is False and "no supporting source quotes" in d["detail"]
    assert card["infra_error"] is False and all(not it["quotes_ok"] for it in card["doctrine_items"])


# ------------------------------------------------------------------------- 9. once per wrong option; one fails

def test_09_distractor_reviewer_called_once_per_wrong_option():
    rev = FakeReviewer()
    card = run(final=finished(game()), runtime=full_runtime(reviewer=rev))  # 2 mcq rounds
    distractor_prompts = [p for p in rev.prompts if "DISTRACTOR" in p]
    assert len(distractor_prompts) == 6 and len(rev.prompts) == 3 + 6
    assert [it["id"] for it in card["doctrine_items"] if it["pass"] == 2] == \
        ["q2:A", "q2:C", "q2:D", "q3:A", "q3:C", "q3:D"]
    assert sum("OPTION: answer A" in p for p in distractor_prompts) == 2
    assert not any("answer B" in p for p in distractor_prompts)

    rev = FakeReviewer()
    card = run(final=finished(produce_game()), runtime=full_runtime(reviewer=rev))
    assert not any("DISTRACTOR" in p for p in rev.prompts) and len(rev.prompts) == 4
    assert "no distractors (produce-only game)" in gate(card, "doctrine")["detail"]
    assert gate(card, "doctrine")["passed"] is True

    rev = FakeReviewer(lambda n, p: bad_reply("states false law as fact")
                       if "DISTRACTOR" in p and "OPTION: answer C" in p else ok_reply())
    card = assert_schema(run(runtime=full_runtime(reviewer=rev)))
    d = gate(card, "doctrine")
    assert d["passed"] is False and "2/3 distractors ok" in d["detail"] and "false law" in d["detail"]


# ------------------------------------------------------------------------------- 10. mixed content + infra

def test_10_content_failure_plus_infra_failure_is_blocked_not_unavailable():
    rt = rtmod()
    card = assert_schema(run(unverified=["Case C-6/90 para 99"],
                             runtime=full_runtime(reviewer=FakeReviewer([rt.GateInfraError("refused")]))))
    assert set(card["blocking_failures"]) == {"doctrine", "citations"}
    assert gate(card, "doctrine").get("infra") and not gate(card, "citations").get("infra")
    assert card["infra_error"] is False
    assert da.block_message(card).startswith(docketgen.GATE_BLOCKED)


# ------------------------------------------------------------------- 11. content first, then infra -> content

def test_11_content_failure_before_an_outage_stays_content():
    rt = rtmod()
    rev = FakeReviewer([bad_reply("misstates the rule"), rt.GateInfraError("timed out")])
    card = assert_schema(run(runtime=full_runtime(reviewer=rev)))
    d = gate(card, "doctrine")
    assert d["passed"] is False and "infra" not in d and card["infra_error"] is False
    assert len(rev.prompts) == 2                                            # breaker still stops the calls
    assert da.block_message(card).startswith(docketgen.GATE_BLOCKED)


# ------------------------------------------------------------------------------------- 12. circuit breaker

def test_12_first_outage_stops_all_further_reviewer_calls():
    rt = rtmod()
    rev = FakeReviewer([rt.GateInfraError("connection refused")])
    card = run(runtime=full_runtime(reviewer=rev))
    assert len(rev.prompts) == 1 and card["reviewer_calls"] == 1
    assert "7 review(s) skipped" in gate(card, "doctrine")["detail"]
    assert [it["infra"] for it in card["doctrine_items"]] == [True]


# ------------------------------------------------------------------------------------------------ 13. budget

def test_13_doctrine_budget_skips_remaining_calls_as_infra(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_DOCTRINE_BUDGET_S", "1500")
    ticks = iter(range(0, 10**7, 1000))                                     # each look at the clock: +1000 s
    rev = FakeReviewer()
    card = assert_schema(run(runtime=full_runtime(reviewer=rev, clock=lambda: next(ticks))))
    assert len(rev.prompts) == 1 and card["reviewer_calls"] == 1
    assert card["budget_exhausted"] is True
    d = gate(card, "doctrine")
    assert d["passed"] is False and "budget exhausted" in d["infra"]
    assert card["infra_error"] is True and da.block_message(card).startswith(docketgen.GATE_UNAVAILABLE)


# ---------------------------------------------------------------- 14. polish-only list; the empty state

def test_14_polish_only_enforce_list_falls_back_to_all(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", "polish")
    card = assert_schema(run())
    assert card["enforced"] == list(da.DESIGN_MANDATORY) and "polish" in card["config_warning"]
    assert gate(card, "polish")["mandatory"] is False


def test_14b_a_card_with_no_mandatory_gate_never_passes_and_is_not_infra():
    harness = da._gates().harness
    empty = harness.build_card({"title": "t"}, [{"name": "polish", "passed": True, "mandatory": False,
                                                 "detail": "", "infra": "GateInfraError: x"}])
    assert empty["overall_pass"] is False and empty["blocking_failures"] == []
    assert da.card_infra_error(empty) is False
    assert da.block_message(empty) == f"{docketgen.GATE_BLOCKED}: no enforced gate passed"


# --------------------------------------------------------------------------------------- 15. vacuous passes

def test_15_vacuous_inputs_never_pass():
    g = mixed_game()
    g["scenes"] = [s for s in g["scenes"] if not s.get("quiz")]
    assert da._irac_rules(g)                                                 # the IRAC verdict is KEPT
    card = assert_schema(run(final=finished(g)))
    t, d = gate(card, "terminology"), gate(card, "doctrine")
    assert t["passed"] is False and "no rounds" in t["detail"]
    assert d["passed"] is False and "no rounds" in d["detail"]
    assert card["reviewer_calls"] == 0                                      # a verdict alone is never reviewed

    empty_src = src_keyed("")                                                # header only, no text
    card = assert_schema(run(final=finished(keyed_=empty_src), keyed_=empty_src))
    t = gate(card, "terminology")
    assert t["passed"] is False and "no source text" in t["detail"]
    assert gate(card, "doctrine")["passed"] is False

    g = mixed_game()
    for o in g["scenes"][4]["quiz"]["options"]:
        o["correct"] = True                                                 # no wrong option left
    card = assert_schema(run(final=finished(g)))
    d = gate(card, "doctrine")
    assert d["passed"] is False and "malformed mcq: no distractors found" in d["detail"]


# ------------------------------------------------------------------------------- 16. GateConfigError, no network

def test_16_refused_reviewer_config_is_content_with_a_warning_and_no_network(monkeypatch):
    rt = rtmod()

    def no_network(*a, **k):
        raise AssertionError("network attempted")

    monkeypatch.setattr(rt, "_post_json", no_network)
    monkeypatch.setattr(rt._OPENER, "open", no_network)
    monkeypatch.setenv("CF_STUDIO_REVIEW_MODEL", "claude-x")
    runtime = full_runtime()
    del runtime["reviewer"]                                                  # the real factory runs
    card = assert_schema(run(runtime=runtime))
    d = gate(card, "doctrine")
    assert d["passed"] is False and "refused" in d["detail"] and "infra" not in d
    assert card["infra_error"] is False and "GateConfigError" in card["config_warning"]
    assert card["reviewer_calls"] == 0 and da.block_message(card).startswith(docketgen.GATE_BLOCKED)


# ---------------------------------------------------------------------------------------------- 17. lexicon

def _lexicon_file(stem):
    tl = da._gates().terminology_lock
    return json.loads((tl.LEXICON_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def test_17_course_lexicon_mapping(monkeypatch):
    card = run(course={"id": "eu", "slug": "eu"})
    assert card["lexicon_version"] == _lexicon_file("eu-law")["version"]

    card = assert_schema(run(course={"id": "c42", "slug": "maritime-law"}))
    assert card["lexicon_version"] == "fallback" and "maritime-law" in card["config_warning"]
    assert gate(card, "terminology")["passed"] is True                       # fallback runs, not auto-failed

    card = assert_schema(run(course={"id": "c43", "slug": "x" * 49}))
    t = gate(card, "terminology")
    assert t["passed"] is False and "bad course code" in t["detail"] and card["lexicon_version"] == ""
    assert card["blocking_failures"] == ["terminology"]

    monkeypatch.setenv("CF_STUDIO_LEXICON_MAP", " c44 = property , other=pil")
    card = run(course={"id": "c44", "slug": "my-property"})
    assert card["lexicon_version"] == _lexicon_file("property")["version"]

    monkeypatch.setenv("CF_STUDIO_LEXICON_MAP", "garbage-without-equals")
    card = run(course={"id": "prop", "slug": "prop"})
    assert card["lexicon_version"] == _lexicon_file("property")["version"]   # alias still applies
    assert "CF_STUDIO_LEXICON_MAP malformed" in card["config_warning"]


# ------------------------------------------------------------------------------------ 18. block_message safety

@pytest.mark.parametrize("card", [None, {}, {"infra_error": "true"}, "card", 7,
                                  {"blocking_failures": "doctrine"}, {"blocking_failures": [object()]},
                                  {"infra_error": True, "blocking_failures": ["doctrine"], "gates": "x"},
                                  {"blocking_failures": [f"gate{i}" for i in range(500)]}])
def test_18_block_message_never_raises(card):
    msg = da.block_message(card)
    assert isinstance(msg, str) and len(msg) <= 300
    assert msg.startswith((docketgen.GATE_BLOCKED, docketgen.GATE_UNAVAILABLE))


# ----------------------------------------------------------------------------------- 20. inputs not mutated

def test_20_inputs_are_not_mutated():
    k = src_keyed()
    final, course = finished(keyed_=k), dict(COURSE)
    issues, unverified = [{"where": "q1", "problem": "p", "severity": "low"}], []
    before = copy.deepcopy((final, k, course, issues, unverified))
    run(final=final, keyed_=k, course=course, issues=issues, unverified=unverified)
    assert (final, k, course, issues, unverified) == before


# ---------------------------------------------------------------------------------- 21. a heartbeat that raises

def test_21_a_raising_heartbeat_never_fails_a_gate():
    def bad_beat():
        raise ConnectionError("db blip")

    card = assert_schema(run(heartbeat=bad_beat))
    assert card["overall_pass"] is True and card["heartbeat_errors"] > card["reviewer_calls"] > 0


# ------------------------------------------------------------------------------------------ 22. outer guard

def test_22_an_adapter_bug_returns_the_minimal_fallback_card(monkeypatch):
    def broken_loader():
        raise ImportError("gates gone")

    monkeypatch.setattr(da, "_gates", broken_loader)
    card = assert_schema(da.gate_docket(finished(), src_keyed(), [], COURSE, issues=[], unverified=[],
                                        mode="enforce"))
    assert card["blocking_failures"] == ["adapter"] and card["overall_pass"] is False
    assert card["infra_error"] is False and card["mode"] == "enforce" and card["game"]["gid"] == "gabc"
    assert "ImportError: gates gone" in card["gates"][0]["detail"]
    assert da.block_message(card) == f"{docketgen.GATE_BLOCKED}: adapter"
    card = assert_schema(da.gate_docket(None, None, None, None, mode=None))   # garbage in: still a card
    assert card["overall_pass"] is False and card["mode"] == "enforce"


# ------------------------------------------------------------------------------------------ 23. unknown mode

def test_23_unknown_mode_is_recorded_as_enforce():
    card = assert_schema(run(mode="on"))
    assert card["mode"] == "enforce" and "unknown gate mode 'on'" in card["config_warning"]


# ----------------------------------------------------------------------------- 25, 31. relevance windows

FILL = "Filler words lorem ipsum dolor sit amet consectetur. "


def _paragraphs(n_chars, plant=None, at=0):
    """Paragraph text of n_chars with `plant` as its own paragraph starting near offset `at`."""
    para = FILL * 3 + "\n\n"
    head = (para * (at // len(para) + 1))[:at]
    head = head[:head.rfind("\n\n") + 2] if plant else head
    body = head + (plant + "\n\n" if plant else "")
    return (body + para * ((n_chars - len(body)) // len(para) + 1))[:n_chars]


SUPPORT = "The Francovich doctrine requires a sufficiently serious breach of Union law by the Member State."


def test_25_windowing_finds_the_supporting_passage_deep_in_a_long_source():
    k = src_keyed(_paragraphs(40_000), _paragraphs(40_000, SUPPORT, 30_000), _paragraphs(40_000))
    assert 29_000 < k["S2"]["text"].index(SUPPORT) <= 30_000
    gen = "QUESTION: Advise her.\nCORRECT ANSWER: Francovich requires a sufficiently serious breach of Union law"
    src = da.doctrine_source_text(["S1", "S2", "S3"], k, gen, cap=32_000)
    assert len(src) <= 32_000 and SUPPORT in src
    assert all(f"[{key}] " in src for key in ("S1", "S2", "S3"))
    dr = da._gates().doctrinal_review
    assert dr.unverified_quotes(src, [SUPPORT]) == []
    assert SUPPORT not in da.cited_source_text(["S1", "S2", "S3"], k)        # the S3 prefix cut misses it


GAPLESS = "Filler words lorem ipsum dolor sit amet consectetur adipiscing. "   # no paragraph breaks at all
RELEVANT = "Francovich state liability sufficiently serious breach. "


def _gapless():
    """40,000 chars, no blank lines, so chunk bounds fall at exact 2,000 multiples. Chunks 9, 10 and 12 are
    relevant; unique markers straddle 20,000 (adjacent kept chunks) and sit at 22,000 / 24,000 (a gap)."""
    text = list((GAPLESS * 700)[:40_000])

    def put(at, s):
        text[at:at + len(s)] = list(s)

    for start in (18_000, 20_000, 24_000):
        put(start, (RELEVANT * 40)[:2_000])
    put(19_980, "ALPHA-BRAVO-CHARLIE-DELTA-ECHO-FOXTROT-GOLF")              # crosses 20,000
    put(21_985, "HOTEL-INDIA-END")                                          # last chars of chunk 10
    put(24_000, "JULIET-KILO-START")                                        # first chars of chunk 12
    return "".join(text)


def test_25b_quotes_across_adjacent_chunks_verify_and_across_a_gap_fail():
    text = _gapless()
    k = docketgen.source_keys([{"name": "big.pdf", "text": text}])
    gen = "Francovich: state liability needs a sufficiently serious breach"
    src = da.doctrine_source_text(["S1"], k, gen, cap=6_100)
    assert src.startswith("[S1] big.pdf\n") and src.count(da.GAP) == 1
    dr = da._gates().doctrinal_review
    assert dr.unverified_quotes(src, ["ALPHA-BRAVO-CHARLIE-DELTA-ECHO-FOXTROT-GOLF"]) == []   # adjacent: verbatim
    assert dr.unverified_quotes(src, ["HOTEL-INDIA-END JULIET-KILO-START"]) != []              # across the gap
    assert "HOTEL-INDIA-END" + da.GAP + "JULIET-KILO-START" in src


def test_31_windows_are_deterministic_and_in_source_order():
    text = _gapless()
    k = docketgen.source_keys([{"name": "big.pdf", "text": text}])
    gen = "Francovich: state liability needs a sufficiently serious breach"
    a = da.doctrine_source_text(["S1"], k, gen, cap=6_100)
    assert a == da.doctrine_source_text(["S1"], copy.deepcopy(k), gen, cap=6_100)
    assert a.index("ALPHA-BRAVO") < a.index("HOTEL-INDIA-END") < a.index("JULIET-KILO-START")
    assert da.doctrine_source_text(["S1"], k, "", cap=100_000) == "[S1] big.pdf\n" + text   # fits: whole


def test_31b_a_reviewer_quote_that_copies_the_gap_joiner_fails_doctrine(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_DOCTRINE_SOURCE_CAP", "6100")
    text = list((GAPLESS * 700)[:40_000])
    for start in (6_000, 14_000):                                           # chunks 3 and 7: never adjacent
        text[start:start + 2_000] = list(("Advise because the rule applies. " * 70)[:2_000])
    k = docketgen.source_keys([{"name": "big.pdf", "text": "".join(text)}])  # words every item's text uses

    def gap_quoter(n, prompt):
        src = prompt.split("SOURCE:\n", 1)[1]
        i = src.find(da.GAP)
        assert i > 0, "expected a windowed source with a gap"
        return ok_reply(src[i - 20:i] + da.GAP + src[i + len(da.GAP):i + len(da.GAP) + 20])

    rev = FakeReviewer(gap_quoter)
    card = assert_schema(run(final=finished(game(), k), keyed_=k, runtime=full_runtime(reviewer=rev)))
    d = gate(card, "doctrine")
    assert d["passed"] is False and "omitted gap" in d["detail"]
    assert all(it["keys_windowed"] == ["S1"] and not it["ok"] for it in card["doctrine_items"])


# --------------------------------------------------------------------------- 26. no raw reasoning on the card

def test_26_card_never_carries_raw_reviewer_text():
    rev = FakeReviewer(lambda n, p: f"<think>{SENTINEL} long private reasoning</think>" + bad_reply("weak"))
    card = assert_schema(run(runtime=full_runtime(reviewer=rev)))
    assert gate(card, "doctrine")["passed"] is False
    assert SENTINEL not in json.dumps(card, ensure_ascii=False)


# --------------------------------------------------------------------------- 27. messy real reviewer output

MESSY = {
    "draft_in_reasoning_then_final_false": (
        '<think>draft {"ok": true, "issues": [], "quotes": ["' + QUOTE + '"]}</think>'
        '{"ok": false, "issues": ["final says no"], "quotes": []}', False),
    "fenced_json": ('```json\n' + ok_reply() + '\n```', True),
    "conversational_preamble": ("Sure, here is my verdict after careful review:\n" + ok_reply(), True),
    "raw_newline_in_quote": ('{"ok": true, "issues": [], "quotes": ["State liability needs a\nsufficiently '
                             'serious breach"]}', True),
    "unparseable": ("I think it is mostly fine, honestly.", False),
}


@pytest.mark.parametrize("case", sorted(MESSY))
def test_27_messy_reviewer_output_gives_a_clean_verdict(case):
    reply, expected = MESSY[case]
    card = assert_schema(run(runtime=full_runtime(reviewer=FakeReviewer(lambda n, p: reply))))
    assert gate(card, "doctrine")["passed"] is expected
    assert card["infra_error"] is False


# ----------------------------------------------------------------------------- 28. malformed upstream signals

@pytest.mark.parametrize("issues", [None, "x", [{}], [{"severity": "HIGH?"}], [1]], ids=repr)
def test_28_malformed_reviewer_issues_fail_closed(issues):
    card = assert_schema(run(issues=issues))
    g = gate(card, "reviewer_high")
    assert g["passed"] is False and "malformed" in g["detail"] and "reviewer_high" in card["blocking_failures"]


@pytest.mark.parametrize("unverified", [None, False, [None]], ids=repr)
def test_28b_malformed_citation_results_fail_closed(unverified):
    card = assert_schema(run(unverified=unverified))
    g = gate(card, "citations")
    assert g["passed"] is False and "malformed" in g["detail"] and "citations" in card["blocking_failures"]


def test_28c_well_formed_signals_gate_as_expected():
    card = run(issues=[{"where": "q2", "problem": "wrong limb", "severity": "high"}], unverified=["C-6/90"])
    assert "wrong limb" in gate(card, "reviewer_high")["detail"] and "C-6/90" in gate(card, "citations")["detail"]
    assert set(card["blocking_failures"]) == {"reviewer_high", "citations"}


# ------------------------------------------------------------------------------------- 29. cap forwarding

def test_29_doctrine_and_terminology_see_past_the_s3_cap():
    deep = "DEEP-SENTENCE: State liability needs a sufficiently serious breach of Union law."
    text = _paragraphs(30_000, deep, 25_000)
    k = src_keyed(text)
    rev = FakeReviewer(lambda n, p: ok_reply(deep))
    card = run(final=finished(game(), k), keyed_=k, runtime=full_runtime(reviewer=rev))
    first = rev.prompts[0]
    source_section = first.split("SOURCE:\n", 1)[1].split("\n\nGENERATED:", 1)[0]
    assert deep in first and len(source_section) > da.SOURCE_CAP
    assert gate(card, "doctrine")["passed"] is True

    term_text = _paragraphs(40_000, "Here state liability arises.", 35_000)
    assert 34_000 < term_text.index("state liability") <= 35_100
    k = src_keyed(term_text)
    g = game()
    for s in g["scenes"]:
        for o in (s.get("quiz") or {}).get("options") or []:
            if o["correct"]:
                o["text"] = "state responsibility applies"
    card = run(final=finished(g, k), keyed_=k, runtime=full_runtime(reviewer=FakeReviewer(lambda n, p: bad_reply())))
    t = gate(card, "terminology")
    assert t["passed"] is False and "state liability->state responsibility" in t["detail"]


# ------------------------------------------------------------------------------ 30. block_message length

def test_30_block_message_is_capped_on_both_branches():
    infra_card = {"infra_error": True, "blocking_failures": [f"g{i}" for i in range(5)],
                  "gates": [{"name": f"g{i}", "infra": "R" * 1000} for i in range(5)]}
    msg = da.block_message(infra_card)
    assert msg.startswith(f"{docketgen.GATE_UNAVAILABLE}: g0: RRR") and len(msg) <= 300
    blocked = {"infra_error": False, "blocking_failures": [f"gate_{i}" for i in range(500)]}
    msg = da.block_message(blocked)
    assert msg.startswith(f"{docketgen.GATE_BLOCKED}: gate_0, gate_1") and len(msg) <= 300


# --------------------------------------------------- D1-D5: owner decisions (unwired gates, lexicon aliases)

def test_d1_unwired_gates_are_advisory_and_never_block():
    """Until S6/S7 land, playability/accessibility/polish show as 'not wired' with mandatory False."""
    runtime = {"reviewer": FakeReviewer()}                                   # no probes, no screenshot
    card = assert_schema(run(runtime=runtime))
    assert card["not_wired"] == ["playability", "accessibility", "polish"]
    for name in card["not_wired"]:
        g = gate(card, name)
        assert g["passed"] is False and g["mandatory"] is False and g["not_wired"] is True
        assert g["detail"].startswith("not wired")
    assert gate(card, "playability")["designed_mandatory"] is True
    assert card["enforced"] == ["terminology", "doctrine", "retrieval", "self_contained", "citations",
                                "reviewer_high"]
    assert card["overall_pass"] is True and card["blocking_failures"] == [] and card["config_warning"] == ""


def test_d2_an_enforce_list_naming_an_unwired_gate_drops_it(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", "a11y, citations")
    card = assert_schema(run(runtime={"reviewer": FakeReviewer()}))
    assert card["enforced"] == ["citations"] and "accessibility is not wired yet" in card["config_warning"]
    assert gate(card, "accessibility")["mandatory"] is False and card["overall_pass"] is True
    monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", "playability")              # nothing enforceable left
    card = assert_schema(run(runtime={"reviewer": FakeReviewer()}))
    assert card["enforced"] == ["terminology", "doctrine", "retrieval", "self_contained", "citations",
                                "reviewer_high"]
    assert "left no enforceable gate" in card["config_warning"]


def test_d3_wired_probes_make_the_gates_enforceable():
    """The override path for S6/S7: once a runtime supplies the probe, a failing playthrough blocks."""
    card = assert_schema(run(runtime=full_runtime(page_probe=BrokenPage())))
    p = gate(card, "playability")
    assert p["mandatory"] is True and p["passed"] is False and "not_wired" not in p
    assert card["blocking_failures"] == ["playability"] and "playability" in card["enforced"]


@pytest.mark.parametrize("cid,stem", [("eu", "eu-law"), ("prop", "property"), ("pil", "pil")])
def test_d4_alias_table_maps_every_course_to_its_approved_lexicon(cid, stem):
    assert da.LEXICON_ALIASES[cid] == stem
    card = assert_schema(run(course={"id": cid, "slug": cid}))
    f = _lexicon_file(stem)
    assert card["lexicon_version"] == f["version"] and card["lexicon_status"] == f["status"]
    assert card["lexicon_status"].startswith("APPROVED")
    card = run(course={"id": "user-made-7", "slug": cid})                    # slug alias when the id is unknown
    assert card["lexicon_version"] == f["version"]


def test_d5_env_lexicon_map_overrides_the_alias_table(monkeypatch):
    monkeypatch.setenv("CF_STUDIO_LEXICON_MAP", "eu=pil")
    card = run(course={"id": "eu", "slug": "eu"})
    assert card["lexicon_version"] == _lexicon_file("pil")["version"]
    assert da.lexicon_code({"id": "eu", "slug": "eu"}, []) == "pil"


# ------------------------------------------------------------------------ 19. every path above round-trips

def _scenarios():
    rt = lambda: rtmod()  # noqa: E731
    return {
        "all_pass": lambda mp: run(),
        "infra_only": lambda mp: run(runtime=full_runtime(reviewer=FakeReviewer([rt().GateInfraError("t")]))),
        "unwired": lambda mp: run(runtime={"reviewer": FakeReviewer()}),
        "malformed_issues": lambda mp: run(issues="x", unverified=None),
        "oversized": lambda mp: run(issues=[{"where": "w", "problem": "ü" * 100_000, "severity": "high"}]),
        "fallback": lambda mp: (mp.setattr(da, "_gates", lambda: 1 / 0), da.gate_docket({}, {}, [], {}))[1],
        "unknown_mode": lambda mp: run(mode=object()),
        "bad_lexicon": lambda mp: run(course={"slug": "Not A Slug"}),
        "non_dict_game": lambda mp: run(final=["not", "a", "game"]),
    }


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_19_every_card_path_is_json_round_trippable(monkeypatch, name):
    card = assert_schema(_scenarios()[name](monkeypatch))
    assert json.loads(json.dumps(card)) == card
    assert isinstance(da.block_message(card), str)


# ==================================================================== S4 fix round 1 (strict review + batch review)

def test_r1_a_blank_round_fails_terminology():
    """An mcq round whose correct option and every teaching are blank projects to '' and must not pass."""
    g = mixed_game()
    for o in g["scenes"][4]["quiz"]["options"]:
        o["teaching"] = ""
        if o["correct"]:
            o["text"] = ""
    item = by_id(da.items_for_terminology(g, src_keyed()))["q4"]
    assert item["generated_text"] == "" and item["cites"] == ["S1"]         # cited, so only blankness fails
    t = gate(assert_schema(run(final=finished(g))), "terminology")
    assert t["passed"] is False and "q4: no text to check" in t["detail"]


def _synonym_round(cites):
    """mcq round 4 whose correct answer swaps 'state liability' for 'state responsibility', citing `cites`."""
    g = mixed_game()
    for o in g["scenes"][4]["quiz"]["options"]:
        o["cites"], o["teaching"] = list(cites), f"plain {o['key']}"
        if o["correct"]:
            o["text"] = "state responsibility applies"
    return g


def test_r1_an_uncited_item_fails_terminology_instead_of_being_checked_against_everything():
    """Batch hole (1): checked against ALL sources, a source that happens to use the synonym silenced the swap."""
    k = src_keyed(SRC, "Older texts speak of state responsibility in this context.")
    g = _synonym_round(())
    assert by_id(da.items_for_terminology(g, k))["q4"]["cites"] == []
    t = gate(assert_schema(run(final=finished(g, k), keyed_=k)), "terminology")
    assert t["passed"] is False and "q4: uncited" in t["detail"]


def test_r1_terminology_runs_per_cited_source_so_one_source_cannot_silence_another():
    """Batch hole (1): S1 says 'state liability', S2 uses the synonym. Joined, S2 silenced the check on S1."""
    k = src_keyed(SRC, "Older texts speak of state responsibility in this context.")
    t = gate(assert_schema(run(final=finished(_synonym_round(("S1", "S2")), k), keyed_=k)), "terminology")
    assert t["passed"] is False and "q4: state liability->state responsibility" in t["detail"]
    ok = gate(run(final=finished(_synonym_round(("S2",)), k), keyed_=k), "terminology")   # S2 alone: no term
    assert ok["passed"] is True, ok["detail"]


def test_r1_terminology_sees_past_the_per_key_s3_cap_with_several_cited_sources():
    """Batch hole (2): with 3 cited keys the S3 cap gives each 12000//3 chars; the term sits at ~8000 in S2."""
    k = docketgen.source_keys([{"name": "a.pdf", "text": _paragraphs(10_000)},
                               {"name": "b.pdf", "text": _paragraphs(10_000, "Here state liability arises.", 8_000)},
                               {"name": "c.pdf", "text": _paragraphs(10_000)}])
    g = _synonym_round(("S1", "S2", "S3"))
    assert "state liability" not in by_id(da.items_for_terminology(g, k))["q4"]["source_text"]   # S3 cap hides it
    rev = FakeReviewer(lambda n, p: bad_reply())
    t = gate(run(final=finished(g, k), keyed_=k, runtime=full_runtime(reviewer=rev)), "terminology")
    assert t["passed"] is False and "q4: state liability->state responsibility" in t["detail"]


def test_r1_a_quote_of_a_source_header_never_verifies():
    """'[S1] Week 3 lecture.pdf' is the adapter's own header, not source text."""
    rev = FakeReviewer(lambda n, p: ok_reply("[S1] Week 3 lecture.pdf"))
    card = assert_schema(run(runtime=full_runtime(reviewer=rev)))
    assert gate(card, "doctrine")["passed"] is False
    assert not any(it["ok"] or it["quotes_ok"] for it in card["doctrine_items"])


ELIDED = "State liability requires a breach […] that is sufficiently serious under Union law. "
ELIDED_QUOTE = "State liability requires a breach […] that is sufficiently serious"


def test_r1_a_real_elision_inside_one_window_segment_verifies(monkeypatch):
    """CJEU text carries real '[…]' elisions. Quoted faithfully from inside one kept segment of a windowed
    source, the quote verifies; only a quote that spans the adapter's own gap fails (test 31b)."""
    monkeypatch.setenv("CF_STUDIO_DOCTRINE_SOURCE_CAP", "6100")
    k = docketgen.source_keys([{"name": "judgment.pdf", "text": (ELIDED * 600)[:40_000]}])
    rev = FakeReviewer(lambda n, p: ok_reply(ELIDED_QUOTE))
    card = assert_schema(run(final=finished(game(), k), keyed_=k, runtime=full_runtime(reviewer=rev)))
    assert all(it["keys_windowed"] == ["S1"] for it in card["doctrine_items"])
    assert all(it["ok"] and it["quotes_ok"] for it in card["doctrine_items"]), card["doctrine_items"]
    assert gate(card, "doctrine")["passed"] is True


def test_r1_bundle_cache_survives_a_concurrent_clear(monkeypatch):
    """Another writer thread may clear the cache between a membership test and the lookup."""
    class RacyCache(dict):
        def __contains__(self, key):
            hit = super().__contains__(key)
            self.clear()                                                    # the other thread wins the race
            return hit

    monkeypatch.setattr(da, "_bundle_cache", RacyCache({"h1": "cached bundle"}))
    assert da.player_bundle_text("h1") == "cached bundle"


@pytest.mark.parametrize("name", ["retrieval", "self_contained", "citations", "reviewer_high", "playability"])
def test_r1_gate_infra_error_in_any_gate_is_classified_before_run_gate_swallows_it(monkeypatch, name):
    """Batch hole (6): an outage must reach the card as infra (GATE_UNAVAILABLE, counted toward
    max_infra_failures by S8), not as a content failure (GATE_BLOCKED, max_failures)."""
    rt = rtmod()

    def outage(ctx):
        raise rt.GateInfraError(f"{name} backend down")

    monkeypatch.setattr(da, f"_g_{name}", outage)
    card = assert_schema(run())
    g = gate(card, name)
    assert g["passed"] is False and "GateInfraError" in g["infra"] and "backend down" in g["infra"]
    assert card["blocking_failures"] == [name] and card["infra_error"] is True
    assert da.block_message(card).startswith(docketgen.GATE_UNAVAILABLE)


# ==================================================================== S4 fix round 2 (adversarial review)

def _cite_only_q4():
    """mcq round 4 whose correct answer and every teaching are just a cite marker: cited, non-blank, no words."""
    g = mixed_game()
    for o in g["scenes"][4]["quiz"]["options"]:
        o["teaching"] = "[S1]"
        if o["correct"]:
            o["text"] = "[S1]"
    return g


def test_r2_a_cite_marker_only_round_fails_terminology_and_doctrine_under_full_enforcement():
    """Round-2 BLOCKING: '[S1]' got past the 'no text to check' guard and the whole card passed."""
    g = _cite_only_q4()
    item = by_id(da.items_for_terminology(g, src_keyed()))["q4"]
    assert item["generated_text"].strip() and item["cites"] == ["S1"]      # not blank, cited: only words fail
    rev = FakeReviewer()
    card = assert_schema(run(final=finished(g), runtime=full_runtime(reviewer=rev)))
    assert card["enforced"] == list(da.DESIGN_MANDATORY)
    t, d = gate(card, "terminology"), gate(card, "doctrine")
    assert t["passed"] is False and "q4: no text to check" in t["detail"]
    assert d["passed"] is False and "q4: no text to check" in d["detail"]  # each gate fails on its own
    assert card["overall_pass"] is False
    assert not any("Advise her." in p and "CORRECT ANSWER: [S1]" in p for p in rev.prompts)  # never reviewed


@pytest.mark.parametrize("label", ["blank q4", "cite-only q4", "cite-only verdict", "empty spot", "empty mcq",
                                   "cite-only order"])
def test_r2_doctrine_alone_fails_a_round_with_no_answer_words_without_calling_the_reviewer(monkeypatch, label):
    """Round-2 NON-BLOCKING: with doctrine enforced but not terminology, a wordless round passed because the
    reviewer saw only 'QUESTION: ...'. The shared pre-check runs on the round's answer content in pass 1."""
    monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", "doctrine")
    irac = {"irac": [{"rule": "State liability needs a sufficiently serious breach [S1]"}]}
    bad = "q4"
    if label == "blank q4":
        g = mixed_game()
        for o in g["scenes"][4]["quiz"]["options"]:
            o["teaching"] = ""
            if o["correct"]:
                o["text"] = ""
        g = finished(g)
    elif label == "cite-only q4":
        g = finished(_cite_only_q4())
    elif label == "cite-only verdict":
        g, bad = finished(), "verdict"
        g["verdict"]["irac"] = [{"rule": "[S1]"}]
    else:
        bad = "q1"
        q = {"empty spot": {"id": "q1", "kind": "spot", "cites": ["S1"]},
             "empty mcq": {"id": "q1", "options": [{"key": "opt1", "correct": True, "teaching": "[S1] [S1 p.4]"},
                                                   {"key": "B"}]},
             "cite-only order": {"id": "q1", "kind": "order", "teaching": "[S1]"}}[label]
        g = {"id": "g", "scenes": [{"id": "s1", "quiz": q}], "verdict": irac}
    rev = FakeReviewer()
    card = assert_schema(run(final=g, runtime=full_runtime(reviewer=rev)))
    assert card["enforced"] == ["doctrine"]
    d = gate(card, "doctrine")
    assert d["passed"] is False and f"{bad}: no text to check" in d["detail"], d["detail"]
    assert card["overall_pass"] is False
    rec = next(r for r in card["doctrine_items"] if r["id"] == bad and r["pass"] == 1)
    assert rec["ok"] is False and rec["issues"] == ["no text to check"]
    assert card["reviewer_calls"] == len(rev.prompts)                       # the blank item was never sent


def test_r2_real_fixtures_have_no_wordless_rounds():
    """The pre-check must not false-block the good games the rest of the suite relies on."""
    for g in (finished(), finished(game()), finished(produce_game())):
        assert not [it["id"] for it in da.items_for_terminology(g, src_keyed()) if da._no_words(it["generated_text"])]


# ==================================================================== S4 fix round 3 (adversarial review)

_DISTRACTOR_HEAD = "DISTRACTOR (the wrong option, including any story text):\n"
_TEACHING_HEAD = "TEACHING (the explanation shown to the player of why this option is wrong):\n"


def _distractor_prompts(rev):
    return [p for p in rev.prompts if _DISTRACTOR_HEAD in p]


def _wordless_distractor_game(label):
    """mixed_game with q4's wrong options emptied of words in one way; the correct option stays intact, so the
    round's terminology text and pass-1 doctrine text still have words. Returns (game, ids of wordless items)."""
    g = mixed_game()
    wrong = [o for o in g["scenes"][4]["quiz"]["options"] if not o["correct"]]
    if label == "all blank, teaching cite-only":                     # the round-3 repro (r3refine.py section 1)
        for o in wrong:
            o.update(text="", story="", teaching="[S1]")
        bad = wrong
    elif label == "one option text cite-only":
        wrong[0]["text"], wrong[0]["story"] = "[S1] [S1 p.4]", ""
        bad = wrong[:1]
    elif label == "one teaching blank":
        wrong[0]["teaching"] = ""
        bad = wrong[:1]
    else:                                                           # "one teaching cite-only"
        wrong[0]["teaching"] = "[S1]\n[S1]"
        bad = wrong[:1]
    return g, {f"q4:{o['key']}" for o in bad}


@pytest.mark.parametrize("enforce", [None, "doctrine"])
@pytest.mark.parametrize("label", ["all blank, teaching cite-only", "one option text cite-only",
                                   "one teaching blank", "one teaching cite-only"])
def test_r3_doctrine_pass2_fails_a_wordless_distractor_without_calling_the_reviewer(monkeypatch, label, enforce):
    """Round-3 BLOCKING: the 'no text to check' pre-check ran in doctrine pass 1 only, so a distractor with no
    words (blank option, teaching '[S1]') was sent to the reviewer with an empty DISTRACTOR block, an ok reply
    passed it, and the card passed. Pass 2 now fails such an item before any reviewer call."""
    if enforce:
        monkeypatch.setenv("CF_STUDIO_ENFORCE_GATES", enforce)
    g, bad = _wordless_distractor_game(label)
    fin = finished(g)
    p2 = da.distractors_for_review(fin, src_keyed())
    assert {d["id"] for d in p2 if da._no_words(d["option_text"]) or da._no_words(d["teaching"])} == bad
    assert not [d["id"] for d in da.rounds_for_doctrine(fin, src_keyed()) if da._no_words(d["generated_text"])]
    rev = FakeReviewer()
    card = assert_schema(run(final=fin, runtime=full_runtime(reviewer=rev)))
    d = gate(card, "doctrine")
    assert d["passed"] is False, d["detail"]
    for i in sorted(bad):
        assert f"{i}: no text to check" in d["detail"], d["detail"]
        rec = next(r for r in card["doctrine_items"] if r["id"] == i and r["pass"] == 2)
        assert rec["ok"] is False and rec["issues"] == ["no text to check"]
    assert card["overall_pass"] is False
    # never sent: exactly the worded distractors reached the reviewer, and no prompt has an empty DISTRACTOR
    # block or a cite-only / empty TEACHING block
    sent = _distractor_prompts(rev)
    assert len(sent) == len(p2) - len(bad), (len(sent), len(p2), bad)
    for p in sent:
        assert _DISTRACTOR_HEAD + "\n" not in p
        assert _TEACHING_HEAD + "\n" not in p and _TEACHING_HEAD + "[S1]\n\n" not in p \
            and _TEACHING_HEAD + "[S1]\n[S1]\n\n" not in p
    assert card["reviewer_calls"] == len(rev.prompts)


def test_r3_real_fixtures_have_no_wordless_distractors():
    """The pass-2 pre-check must not false-block the good games' distractors."""
    for g in (finished(), finished(game()), finished(produce_game())):
        assert not [d["id"] for d in da.distractors_for_review(g, src_keyed())
                    if da._no_words(d["option_text"]) or da._no_words(d["teaching"])]
