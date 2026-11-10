"""The checks a written Case Docket game must pass before he ever sees it (2026-09-29)."""

import docketgen


def game():
    opt = lambda k, ok: {"key": k, "text": f"answer {k}", "correct": ok, "teaching": f"because [S1] {k}", "cites": ["S1"]}
    rnd = lambda n: {"id": f"s{n}", "title": "Examination", "phase": "examination", "set": "courtroom", "action": ["x"],
                     "dialogue": [{"speaker": "JUDGE VOS", "line": "Well?"}],
                     "quiz": {"id": f"q{n}", "question": "Advise her.", "options": [opt("A", False), opt("B", True), opt("C", False), opt("D", False)]}}
    return {"title": "The Canal House", "logline": "l", "case_file": ["Claimant: Anna"],
            "scenes": [{"id": "s1", "title": "Arrival", "phase": "arrival", "set": "street", "action": ["walk"], "dialogue": []},
                       rnd(2), rnd(3),
                       {"id": "s4", "title": "Verdict", "phase": "verdict", "set": "courtroom", "action": ["v"], "dialogue": []},
                       {"id": "s5", "title": "Epilogue", "phase": "epilogue", "set": "generic", "action": ["e"], "dialogue": []}],
            "verdict": {"outcome": "WON", "irac": [{"issue": "i", "rule": "r [S1]", "application": "a", "conclusion": "c"}], "takeaway": "t"},
            "checks": [{"n": 1, "claim": "c", "cites": ["S1"]}]}


def test_a_sound_game_passes():
    assert docketgen.validate(game(), {"S1", "S2"}) == []


def test_each_contract_break_is_named():
    g = game(); g["scenes"][1]["quiz"]["options"][0]["correct"] = True
    assert any("exactly one correct" in p for p in docketgen.validate(g, {"S1"}))
    g = game(); g["scenes"][0]["set"] = "courtroom"
    assert any("arrival must be outdoors" in p for p in docketgen.validate(g, {"S1"}))
    g = game(); g["scenes"][2]["set"] = "castle"
    assert any("unknown set" in p for p in docketgen.validate(g, {"S1"}))
    g = game(); g["scenes"] = [g["scenes"][0], g["scenes"][1], g["scenes"][3], g["scenes"][4]]
    assert any("1 examination round" in p for p in docketgen.validate(g, {"S1"}))
    g = game(); g["scenes"][3], g["scenes"][1] = g["scenes"][1], g["scenes"][3]
    assert any("out of order" in p for p in docketgen.validate(g, {"S1"}))
    assert docketgen.validate("not json", {"S1"}) == ["The writer did not return a game."]


def test_a_citation_to_a_file_that_does_not_exist_is_caught():
    g = game(); g["scenes"][1]["quiz"]["options"][1]["teaching"] = "see [S9 p.4]"
    assert any("S9" in p for p in docketgen.validate(g, {"S1"}))


def test_finish_makes_it_playable_and_stamps_the_verdicts():
    keyed = docketgen.source_keys([{"id": "f1", "name": "Week 3 lecture.pdf", "role": "lecture", "text": "t"}])
    g = docketgen.finish(game(), "gabc", "CF-prop", keyed)
    assert g["id"] == "gabc" and g["course"] == "CF-prop" and g["sources"]["S1"]["file"] == "Week 3 lecture.pdf"
    stamps = [o["stamp"] for o in g["scenes"][1]["quiz"]["options"]]
    assert stamps == ["OVERRULED", "SUSTAINED", "OVERRULED", "OVERRULED"]
    assert g["scenes"][0]["slug"]["int_ext"] == "EXT" and g["scenes"][1]["shots"] == []


def test_sources_block_caps_a_huge_reader():
    keyed = docketgen.source_keys([{"name": "reader.pdf", "text": "R" * 200_000}, {"name": "wg.pdf", "text": "WG notes"}])
    block = docketgen.sources_block(keyed)
    assert block.count("R") <= docketgen.FILE_CHARS + 10 and "WG notes" in block


def test_which_weeks_need_a_game():
    now = 10_000.0
    files = [{"week": "1", "created": 100}, {"week": "2", "created": 500}, {"week": "3", "created": 900}, {"week": "", "created": 950}]
    games = [{"week": "1", "status": "approved", "created": 200, "updated": 200},     # older files: nothing new
             {"week": "2", "status": "discarded", "created": 400, "updated": 400},    # new file since the discard: again
             {"week": "3", "status": "writing", "created": 9_900, "updated": 9_950}]  # being written right now
    assert docketgen.weeks_needing_games(files, games, now) == ["2"]
    games[2]["updated"] = now - docketgen.AUTO_STALE_S - 1                            # a writer that died long ago
    assert docketgen.weeks_needing_games(files, games, now) == ["2"]                   # still newer than the file: not again
    failed = [{"week": "3", "status": "failed", "created": 9_990, "updated": 9_990}]
    assert docketgen.weeks_needing_games(files, failed, now) == ["1", "2"]              # a fresh failure holds week 3 back
    assert docketgen.weeks_needing_games(files, failed, now + 7 * 3600) == ["1", "2", "3"]


# ---------------------------------------------------------------- S8: attempt caps + weekly slots

def _weeks_needing_games_before_s8(files, games, now, failed_backoff_s=6 * 3600):
    """Frozen copy of weeks_needing_games as shipped before S8, the reference the defaults must match."""
    newest_file = {}
    for f in files:
        w = str(f.get("week") or "").strip()
        if w:
            newest_file[w] = max(newest_file.get(w, 0), f.get("created") or 0)
    newest_game, busy = {}, set()
    for g in games:
        w = str(g.get("week") or "")
        if g.get("status") == "writing" and now - (g.get("updated") or 0) < docketgen.AUTO_STALE_S:
            busy.add(w)
        if g.get("status") == "failed" and now - (g.get("updated") or 0) >= failed_backoff_s:
            continue
        newest_game[w] = max(newest_game.get(w, 0), g.get("created") or 0)
    due = [w for w, t in newest_file.items() if w not in busy and t > newest_game.get(w, 0)]
    return sorted(due, key=lambda w: (int(w) if w.isdigit() else 999, w))


def _blocked(week, t, n=1, prefix=docketgen.GATE_BLOCKED):
    return [{"week": week, "status": "failed", "created": t + i, "updated": t + i, "error": f"{prefix}: doctrine"}
            for i in range(n)]


def test_new_parameters_default_to_todays_behaviour():
    import random
    now = 10_000.0
    files = [{"week": "1", "created": 100}, {"week": "2", "created": 500}, {"week": "3", "created": 900}, {"week": "", "created": 950}]
    fixtures = [
        [{"week": "1", "status": "approved", "created": 200, "updated": 200},
         {"week": "2", "status": "discarded", "created": 400, "updated": 400},
         {"week": "3", "status": "writing", "created": 9_900, "updated": 9_950}],
        [{"week": "3", "status": "failed", "created": 9_990, "updated": 9_990}],
        _blocked("2", 600, n=5) + _blocked("3", 1_000, n=9, prefix=docketgen.GATE_UNAVAILABLE),   # error rows are ignored by default
        [],
    ]
    rng = random.Random(8)
    for _ in range(300):   # random rows over every status and both error prefixes
        fixtures.append([{"week": rng.choice(["1", "2", "3", "4", "10", "x"]),
                          "status": rng.choice(["writing", "draft", "approved", "discarded", "failed"]),
                          "created": rng.uniform(0, 30_000), "updated": rng.uniform(0, 30_000),
                          "error": rng.choice(["", docketgen.GATE_BLOCKED + ": x", docketgen.GATE_UNAVAILABLE + ": y", "other"])}
                         for _ in range(rng.randint(0, 12))])
    for games in fixtures:
        for t in (now, now + 7 * 3600, 40_000.0):
            want = _weeks_needing_games_before_s8(files, games, t)
            assert docketgen.weeks_needing_games(files, games, t) == want
            assert docketgen.weeks_needing_games(files, games, t, max_failures=None, max_infra_failures=None, slots=None) == want


def test_max_failures_stops_requeue_until_new_material():
    files = [{"week": "1", "created": 100}]
    later = 100_000.0                                                     # every failure is past its 6 h backoff
    games = _blocked("1", 200, n=2)
    assert docketgen.weeks_needing_games(files, games, later, max_failures=3) == ["1"]       # 2 blocked: try again
    games = _blocked("1", 200, n=3)
    assert docketgen.weeks_needing_games(files, games, later, max_failures=3) == []          # 3 blocked: stop
    assert docketgen.weeks_needing_games(files, games, later) == ["1"]                       # default: re-queues forever
    old = _blocked("1", 50, n=3)                                          # blocked on an older material version
    assert docketgen.weeks_needing_games(files, old, later, max_failures=3) == ["1"]
    files.append({"week": "1", "created": 500})                           # new material lands: quota resets
    assert docketgen.weeks_needing_games(files, games, later, max_failures=3) == ["1"]
    plain = [{"week": "1", "status": "failed", "created": 600 + i, "updated": 600 + i, "error": "Writer broke"} for i in range(5)]
    assert docketgen.weeks_needing_games(files, plain, later, max_failures=3) == ["1"]       # non-gate failures don't count


def test_gates_unavailable_has_its_own_cap():
    files = [{"week": "1", "created": 100}]
    later = 100_000.0
    infra5 = _blocked("1", 200, n=5, prefix=docketgen.GATE_UNAVAILABLE)
    assert docketgen.weeks_needing_games(files, infra5, later, max_failures=3, max_infra_failures=6) == ["1"]  # quota not spent
    infra6 = _blocked("1", 200, n=6, prefix=docketgen.GATE_UNAVAILABLE)
    assert docketgen.weeks_needing_games(files, infra6, later, max_failures=3, max_infra_failures=6) == []     # stops at 6
    assert docketgen.weeks_needing_games(files, infra6, later, max_failures=3) == ["1"]                       # no infra cap given
    mixed = _blocked("1", 200, n=2) + _blocked("1", 300, n=5, prefix=docketgen.GATE_UNAVAILABLE)
    assert docketgen.weeks_needing_games(files, mixed, later, max_failures=3, max_infra_failures=6) == ["1"]   # caps don't add up
    fresh = _blocked("1", later - 60, n=1, prefix=docketgen.GATE_UNAVAILABLE)
    assert docketgen.weeks_needing_games(files, fresh, later, max_failures=3, max_infra_failures=6) == []     # 6 h backoff still holds


def test_weekly_slots_counts_across_courses_and_ignores_failed():
    now = 1_000_000.0
    day = 86400
    rows = [{"status": "draft", "created": now - 1 * day},       # course A
            {"status": "approved", "created": now - 2 * day},    # course B: same owner, same cap (D-11)
            {"status": "failed", "created": now - 1 * day, "error": docketgen.GATE_BLOCKED + ": x"},
            {"status": "failed", "created": now - 1 * day, "error": docketgen.GATE_UNAVAILABLE + ": y"},
            {"status": "discarded", "created": now - 8 * day}]  # outside the 7-day window
    assert docketgen.weekly_slots(rows, 3, now) == 1
    assert docketgen.weekly_slots(rows[:2], 3) == 1                                   # caller pre-filtered the window
    assert docketgen.weekly_slots(rows + [{"status": "writing", "created": now}, {"status": "discarded", "created": now}], 3, now) == 0
    assert docketgen.weekly_slots([], 3, now) == 3
    assert docketgen.weekly_slots(rows, None, now) is None                            # no cap
    assert docketgen.weekly_slots([{"status": "draft", "created": now}] * 5, 3, now) == 0   # never negative


def test_slots_truncate_the_due_list_oldest_week_first():
    now = 1_000_000.0
    files = [{"week": w, "created": 100} for w in ("4", "1", "3", "2")]
    owner_rows = [{"status": "draft", "created": now - 3600}, {"status": "approved", "created": now - 7200},
                  {"status": "failed", "created": now - 60, "error": docketgen.GATE_BLOCKED + ": x"}]
    slots = docketgen.weekly_slots(owner_rows, 3, now)
    assert slots == 1                                                                  # failed rows don't consume slots
    assert docketgen.weeks_needing_games(files, [], now, slots=slots) == ["1"]         # 2 drafts + 4 due, cap 3 -> 1 week
    assert docketgen.weeks_needing_games(files, [], now, slots=0) == []
    assert docketgen.weeks_needing_games(files, [], now, slots=10) == ["1", "2", "3", "4"]
