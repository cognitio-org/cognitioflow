import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from harness import GameSubmission, Runtime, run_gates, render


class GoodPage:
    def console_errors(self):
        return []

    def query(self, selector):
        return True

    def title(self):
        return "The Docket"


class GoodA11y:
    def focus_visible(self):
        return True

    def reduced_motion_respected(self):
        return True

    def min_tap_target_px(self):
        return 44.0

    def min_contrast_ratio(self):
        return 7.0


def good_submission():
    return GameSubmission(
        game_meta={"title": "The Docket: Contract Formation"},
        source_text="A contract requires offer, acceptance, and consideration.",
        generated_text="Spot the issues: was there a valid offer, acceptance, and consideration?",
        game_spec={"interactions": [
            {"prompt": "State the rule for a valid offer", "answer": "..."},
            {"prompt": "Identify the consideration present", "answer": "..."},
            {"prompt": "Apply the acceptance rule to the facts", "answer": "..."},
            {"prompt": "State your conclusion with reasons", "answer": "..."},
        ]},
        required_selectors=["#board", "#submit"],
        screenshot_path="shot.png",
        bundle_text="<script>fetch('/api/catalogue/docket').then(r => r.json())</script>",
    )


def runtime(reviewer, vlm):
    return Runtime(reviewer=reviewer, vlm=vlm, page_probe=GoodPage(), a11y_probe=GoodA11y())


OK_REVIEWER = lambda prompt: '{"ok": true, "issues": []}'
OK_VLM = lambda path: '{"score": 0.82, "notes": "clean, readable"}'


def main():
    # (a) everything passes -> overall pass, no blockers
    card = run_gates(good_submission(), runtime(OK_REVIEWER, OK_VLM))
    assert card["overall_pass"] is True, card
    assert card["blocking_failures"] == [], card

    # (b) doctrine fails (mandatory) -> blocks
    bad_doc = lambda p: '{"ok": false, "issues": ["invented a defence not in the source"]}'
    card = run_gates(good_submission(), runtime(bad_doc, OK_VLM))
    assert card["overall_pass"] is False
    assert "doctrine" in card["blocking_failures"], card

    # (c) polish low (advisory) -> does NOT block
    ugly = lambda path: '{"score": 0.1, "notes": "cramped, low contrast"}'
    card = run_gates(good_submission(), runtime(OK_REVIEWER, ugly))
    assert card["overall_pass"] is True, card
    polish = next(g for g in card["gates"] if g["name"] == "polish")
    assert polish["passed"] is False and polish["mandatory"] is False

    # (d) reviewer raises -> harness fails that gate closed, not a silent pass
    def boom(p):
        raise RuntimeError("model unreachable")
    card = run_gates(good_submission(), runtime(boom, OK_VLM))
    assert card["overall_pass"] is False and "doctrine" in card["blocking_failures"]

    # (e) calls an external AI at play-time -> self_contained blocks
    sub = good_submission()
    sub.bundle_text = "<script>fetch('https://api.anthropic.com/v1/messages')</script>"
    card = run_gates(sub, runtime(OK_REVIEWER, OK_VLM))
    assert card["overall_pass"] is False and "self_contained" in card["blocking_failures"], card

    # render smoke
    md = render(card)
    assert "The Docket" in md and "❌" in md

    print("OK")


main()
