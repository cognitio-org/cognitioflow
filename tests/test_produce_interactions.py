"""Engine support for produce-type interaction kinds (spot / order / slot): docketgen.validate()
branches, the interactions_from_game projection, and the studio retrieval-density gate reading a
sample game as *generation*. The A–D ("mcq") path is covered by test_docketgen.py and stays intact."""
import os
import sys

import docketgen

# The retrieval-density gate lives in studio/gates/ (merged in #183). Import it by path so the test
# works whether or not that dir is on sys.path; skip cleanly if the harness is not present.
_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studio", "gates")
if _GATES not in sys.path:
    sys.path.insert(0, _GATES)
try:
    import retrieval_density
except Exception:  # pragma: no cover - harness absent
    retrieval_density = None


# --------------------------------------------------------------------------- fixtures

def _spot_round():
    return {
        "id": "s2", "title": "The facts", "phase": "examination", "set": "courtroom",
        "action": ["The court sits."], "dialogue": [{"speaker": "JUDGE VOS", "line": "Spot the issues."}],
        "quiz": {
            "id": "q1", "kind": "spot",
            "question": "Select each passage that raises a distinct issue, and name it.",
            "text": "The Member State failed to transpose the directive; Kade suffered loss as a direct result.",
            "teaching": "Two issues: state liability and the loss limb [S1].",
            "cites": ["S1"],
            "answer": {
                "issues": [
                    {"id": "state-liability", "label": "State liability", "spans": [[4, 42]]},
                    {"id": "causal-link", "label": "Causal link", "spans": [[52, 89]]},
                ],
                "decoys": [[0, 3]],
                "taxonomy": [
                    {"id": "state-liability", "label": "State liability"},
                    {"id": "causal-link", "label": "Causal link"},
                    {"id": "proportionality", "label": "Proportionality"},
                ],
                "threshold": 0.7,
            },
        },
    }


def _order_round():
    return {
        "id": "s3", "title": "The rule", "phase": "examination", "set": "courtroom",
        "action": ["The court sits."], "dialogue": [{"speaker": "JUDGE VOS", "line": "Assemble the test."}],
        "quiz": {
            "id": "q2", "kind": "order",
            "question": "Order the Francovich conditions as the court applies them.",
            "teaching": "Rights, then serious breach, then causation [S1].",
            "cites": ["S1"],
            "answer": {
                "sequence": ["e1", "e2", "e3"],
                "bank": [
                    {"id": "e1", "label": "The rule confers rights"},
                    {"id": "e2", "label": "The breach is sufficiently serious"},
                    {"id": "e3", "label": "Causal link to the loss"},
                ],
            },
        },
    }


def _slot_round():
    return {
        "id": "s4", "title": "Apply", "phase": "examination", "set": "courtroom",
        "action": ["The court sits."], "dialogue": [{"speaker": "JUDGE VOS", "line": "Apply the facts."}],
        "quiz": {
            "id": "q3", "kind": "slot",
            "question": "Map each fact onto the element it satisfies.",
            "teaching": "Each fact satisfies one Francovich element [S1].",
            "cites": ["S1"],
            "answer": {
                "elements": [{"id": "e1", "label": "Rights"}, {"id": "e2", "label": "Serious breach"}, {"id": "e3", "label": "Causation"}],
                "facts": [{"id": "f1", "label": "The directive conferred an individual right"},
                          {"id": "f2", "label": "The State ignored a clear ruling"},
                          {"id": "f3", "label": "Kade's loss followed directly"}],
                "key": {"f1": "e1", "f2": "e2", "f3": "e3"},
            },
        },
    }


def produce_game():
    """A sound flagship round built on the produce-type kinds."""
    return {
        "title": "The Harbour Permit", "logline": "A contract signed under threat.", "case_file": ["Claimant: Kade"],
        "scenes": [
            {"id": "s1", "title": "Arrival", "phase": "arrival", "set": "street", "action": ["walk"], "dialogue": []},
            _spot_round(), _order_round(), _slot_round(),
            {"id": "s5", "title": "Verdict", "phase": "verdict", "set": "courtroom", "action": ["The judge rules."], "dialogue": []},
            {"id": "s6", "title": "Epilogue", "phase": "epilogue", "set": "generic", "action": ["Weeks later."], "dialogue": []},
        ],
        "verdict": {"outcome": "WON", "irac": [{"issue": "the issue", "rule": "the rule [S1]", "application": "the application", "conclusion": "the conclusion"}], "takeaway": "the takeaway"},
        "checks": [{"n": 1, "claim": "Duress voids consent.", "cites": ["S1"]}],
    }


# --------------------------------------------------------------------------- validate()

def test_a_sound_produce_game_passes_validate():
    assert docketgen.validate(produce_game(), {"S1", "S2"}) == []


def test_mixed_mcq_and_produce_game_passes_validate():
    g = produce_game()
    g["scenes"].insert(4, {
        "id": "s4b", "title": "Pick", "phase": "examination", "set": "courtroom", "action": ["The court sits."],
        "dialogue": [{"speaker": "JUDGE VOS", "line": "Well?"}],
        "quiz": {"id": "q4", "question": "Advise her.", "options": [
            {"key": "A", "text": "a", "correct": False, "teaching": "no [S1]", "cites": ["S1"]},
            {"key": "B", "text": "b", "correct": True, "teaching": "yes [S1]", "cites": ["S1"]},
            {"key": "C", "text": "c", "correct": False, "teaching": "no [S1]", "cites": ["S1"]},
            {"key": "D", "text": "d", "correct": False, "teaching": "no [S1]", "cites": ["S1"]},
        ]}})
    assert docketgen.validate(g, {"S1"}) == []


def test_each_produce_contract_break_is_named():
    g = produce_game(); g["scenes"][1]["quiz"]["answer"]["issues"] = []
    assert any("at least one issue" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["answer"]["issues"][0]["id"] = "not-in-taxo"
    assert any("not in the taxonomy" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["answer"]["issues"][0]["spans"] = [[50, 10]]
    assert any("spans as [start, end]" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][2]["quiz"]["answer"]["sequence"] = ["e1", "e9"]
    assert any("not in the bank" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][3]["quiz"]["answer"]["key"] = {"f1": "e9"}
    assert any("unknown element" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["options"] = [{"key": "A"}]
    assert any("must not carry 'options'" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["kind"] = "mystery"
    assert any("unknown interaction kind" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["teaching"] = ""
    assert any("has no teaching text" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["text"] = ""
    assert any("no fact text" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["answer"]["issues"][0]["spans"] = [[4, 999]]
    assert any("past the end of the fact text" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][1]["quiz"]["text"] = "A rocket \U0001F680 in the facts"
    assert any("astral characters" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][2]["quiz"]["answer"]["sequence"] = ["e1", "e2"]
    g["scenes"][2]["quiz"]["answer"]["bank"] = g["scenes"][2]["quiz"]["answer"]["bank"][:2]
    assert any("at least three elements" in p for p in docketgen.validate(g, {"S1"}))

    g = produce_game(); g["scenes"][3]["quiz"]["answer"]["elements"] = [{"id": "e1", "label": "Rights"}]
    g["scenes"][3]["quiz"]["answer"]["key"] = {"f1": "e1"}
    assert any("at least two elements" in p for p in docketgen.validate(g, {"S1"}))


# --------------------------------------------------------------------------- projection + gate

def test_interactions_projection_shape():
    inter = docketgen.interactions_from_game(produce_game())
    # 2 spot issues + 1 order + 3 slot key pairs = 6 productive acts, all generation (no options).
    assert len(inter) == 6
    assert all("options" not in i for i in inter)
    assert all(i.get("answer") for i in inter)


def test_sample_game_scores_as_generation():
    if retrieval_density is None:
        import pytest
        pytest.skip("studio retrieval_density gate not importable")
    spec = {"interactions": docketgen.interactions_from_game(produce_game())}
    sc = retrieval_density.score_retrieval(spec)
    assert sc["density"] == 1.0
    assert sc["generation_ratio"] >= 0.4
    assert sc["passes"] is True


def test_todays_mcq_only_game_fails_the_generation_floor():
    """Why the engine extension was needed: an A–D-only game projects to pure recognition."""
    if retrieval_density is None:
        import pytest
        pytest.skip("studio retrieval_density gate not importable")
    mcq_game = {"scenes": [{"id": "s2", "quiz": {"id": "q1", "options": [
        {"key": "A", "correct": False}, {"key": "B", "correct": True},
        {"key": "C", "correct": False}, {"key": "D", "correct": False}]}}]}
    spec = {"interactions": docketgen.interactions_from_game(mcq_game)}
    sc = retrieval_density.score_retrieval(spec)
    assert sc["generation_ratio"] == 0.0
    assert sc["passes"] is False
