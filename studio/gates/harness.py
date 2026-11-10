"""CF Game Studio — Phase-1 gate harness.

Runs every gate over one game submission and assembles the review card for the
human (Matej) sign-off step. This is the thin orchestrator; each gate lives in
its own module and was reviewed independently.

Mandatory gates (BLOCK the game): terminology, doctrine, retrieval, playability,
accessibility. Advisory gates (surfaced, never block): polish/aesthetic.

Every gate runs FAIL-CLOSED: if a gate raises, that gate is recorded as failed,
never silently skipped or passed. A broken game can never slip through on an
exception.
"""
from dataclasses import dataclass

import terminology_lock
import retrieval_density
import doctrinal_review
import playability
import a11y
import aesthetic_judge
import self_contained
import review_card


@dataclass
class GameSubmission:
    game_meta: dict              # {"title": ..., "course": ...} — identity for the card
    source_text: str             # authoritative source passage (ground truth)
    generated_text: str          # the game's generated legal content
    game_spec: dict              # {"interactions": [...]} for the retrieval gate
    required_selectors: list     # DOM selectors the playthrough must find
    screenshot_path: str = ""    # render for the aesthetic judge
    bundle_text: str = ""        # the game's client bundle (HTML+JS) for the self-containment gate


@dataclass
class Runtime:
    reviewer: object             # callable(prompt:str)->str  (doctrinal 2nd model)
    vlm: object                  # callable(image_path:str)->str  (aesthetic judge)
    page_probe: object           # PageProbe (playability)
    a11y_probe: object           # A11yProbe (accessibility)


def run_gate(name: str, mandatory: bool, fn) -> dict:
    """Run one gate fail-closed and return a review_card gate dict.

    `fn()` must return `(passed, detail)`. Anything else fails closed: an exception,
    a non-2-tuple return (bare True, None), or a `detail` whose str() raises.
    Public so callers outside this module (the Phase-2 docket adapter) run each
    gate through exactly the same fail-closed path as `run_gates`.
    """
    try:
        passed, detail = fn()
        detail = str(detail)
    except Exception as e:  # noqa: BLE001 — any gate failure must fail closed
        return {"name": name, "passed": False, "mandatory": mandatory,
                "detail": f"gate error (fail-closed): {e}"}
    # strict: ONLY an explicit boolean True passes. A truthy non-bool (str/dict/None)
    # fails closed, so a gate helper bug can never let a bad game through.
    return {"name": name, "passed": passed is True, "mandatory": mandatory, "detail": detail}


_result = run_gate  # Phase-1 private name; one body so the two can never drift


# Keys only the gate results decide. `extra` in build_card can never set them.
CORE_CARD_KEYS = ("game", "overall_pass", "gates", "blocking_failures")


def build_card(meta: dict, results: list, extra: dict | None = None) -> dict:
    """Assemble a review card from gate results, plus caller metadata in `extra`.

    The verdict keys (CORE_CARD_KEYS) come only from `results`; any of them in `extra`
    is dropped, so e.g. `extra={"overall_pass": True}` can never flip a failing card.
    Each result is normalised fail-closed before the verdict: `passed` counts only if it
    is the literal True, and a gate is mandatory unless `mandatory` is literally False.
    Inputs are not mutated.
    """
    gates = [dict(g, passed=g.get("passed") is True, mandatory=g.get("mandatory", True) is not False)
             for g in results]
    card = review_card.build_review_card(dict(meta), gates)
    for key, value in (extra or {}).items():
        if key not in CORE_CARD_KEYS:
            card[key] = value
    return card


def run_gates(submission: GameSubmission, runtime: Runtime) -> dict:
    """Run all six gates over the submission and return the assembled review card."""
    s = submission
    results = []

    def _terminology():
        viol = terminology_lock.check_terminology(s.source_text, s.generated_text)
        return (not viol,
                "no dangerous term swaps" if not viol
                else "; ".join(f"{v.protected_term}->{v.found_synonym}" for v in viol))
    results.append(_result("terminology", True, _terminology))

    def _doctrine():
        v = doctrinal_review.review_doctrine(s.source_text, s.generated_text, runtime.reviewer)
        return v.ok, ("doctrine sound" if v.ok else "; ".join(v.issues))
    results.append(_result("doctrine", True, _doctrine))

    def _retrieval():
        sc = retrieval_density.score_retrieval(s.game_spec)
        return sc["passes"], f"density={sc['density']:.2f} gen_ratio={sc['generation_ratio']:.2f}"
    results.append(_result("retrieval", True, _retrieval))

    def _playability():
        v = playability.check_playability(runtime.page_probe, s.required_selectors)
        return v.ok, ("plays clean" if v.ok else f"errors={v.errors} missing={v.missing_selectors}")
    results.append(_result("playability", True, _playability))

    def _accessibility():
        v = a11y.check_accessibility(runtime.a11y_probe)
        return v.ok, ("accessible" if v.ok else "; ".join(v.issues))
    results.append(_result("accessibility", True, _accessibility))

    def _self_contained():
        v = self_contained.check_self_contained(s.bundle_text)
        return v.ok, ("no external-AI calls at play-time" if v.ok else "; ".join(v.hits))
    results.append(_result("self_contained", True, _self_contained))

    def _polish():
        v = aesthetic_judge.judge_aesthetics(s.screenshot_path, runtime.vlm)
        return v.ok, f"polish score={v.score:.2f} ({v.notes})"
    results.append(_result("polish", False, _polish))  # advisory — never blocks

    return review_card.build_review_card(s.game_meta, results)


def render(card: dict) -> str:
    """Human-readable markdown for the sign-off step."""
    return review_card.render_markdown(card)
