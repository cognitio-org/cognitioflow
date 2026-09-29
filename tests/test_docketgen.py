"""The checks a written Case Docket game must pass before he ever sees it (2026-09-29)."""
import copy

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
