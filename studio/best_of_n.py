"""CF Game Studio: best-of-N selection with the gates as the filter (model-quality plan, rung 2).

Per requested game the M4 writer kit draws N drafts (4 by default) at the rung-0 sampling settings. Each draft is
gated in two steps:

1. the cheap deterministic gates (terminology, retrieval, self_contained, citations, plus reviewer_high) -
   `deterministic_pass`. NOTE: the M4 kit writes candidates with review=False, so reviewer_high sees no issues and
   passes vacuously there; in offline best-of-N the Thinker doctrine gate is the only legal-accuracy check;
2. only the survivors get the slow Thinker doctrine gate (full card).

The surfaced draft is the one that passes every mandatory gate and scores best on the Thinker review; ties go to
grounding share (verified check quotes), then the share of PRODUCE ROUNDS (spot/slot/order rounds over all rounds),
then id. Two notes from the 2026-11-11 adversarial review:
- WRITER v2 rejects any draft with a quote problem, so every v2 survivor has grounding 1.0 and that key rarely
  decides anything; it is kept for callers that score partly grounded drafts.
- The tie-break deliberately does NOT use generation_ratio: it counts every slot fact and spot issue as an item, so
  a draft that pads extra facts or issues would win ties (a Goodhart pick). Round-level share is fixed by the
  code-chosen mix and cannot be padded.
If none passes, nothing is surfaced and every candidate keeps a reason. `aesthetic_judge` (polish) is advisory: it
never selects (plan section 5 rule 2).

Offline only. Candidates are not drafts: they live in the kit's candidates folder, never in docket_games, and sit
outside the 3-drafts-a-week cap (D-SQ1 default). Pure and stdlib-only.
"""
from __future__ import annotations

DEFAULT_N = 4
DETERMINISTIC_GATES = ("terminology", "retrieval", "self_contained", "citations", "reviewer_high")
NEVER_SELECTS = frozenset({"polish"})


def _gates(card) -> dict:
    out = {}
    for g in (card or {}).get("gates") or [] if isinstance(card, dict) else []:
        if isinstance(g, dict) and isinstance(g.get("name"), str):
            out[g["name"]] = g
    return out


def failing(card, names) -> list:
    """Names (of `names`) whose gate is missing or not literally passed."""
    gates = _gates(card)
    return [n for n in names if not (n in gates and gates[n].get("passed") is True)]


def deterministic_pass(card) -> bool:
    return isinstance(card, dict) and not failing(card, DETERMINISTIC_GATES)


def mandatory_failures(card) -> list:
    """Every enforced gate that did not pass (polish never counts). A card that is not a dict fails as 'card'."""
    if not isinstance(card, dict):
        return ["card"]
    enforced = [n for n in card.get("enforced") or [] if n not in NEVER_SELECTS]
    names = list(dict.fromkeys(list(DETERMINISTIC_GATES) + ["doctrine"] + enforced))
    return failing(card, names)


def doctrine_score(card) -> tuple:
    """(doctrine passed, -failed doctrine items). Higher is better. Missing gate = worst."""
    g = _gates(card).get("doctrine")
    if g is None:
        return (0, -999)
    items = (card or {}).get("doctrine_items") or []
    bad = sum(1 for it in items if not (isinstance(it, dict) and it.get("ok") is True))
    return (1 if g.get("passed") is True else 0, -bad)


def _num(x) -> float:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f else 0.0          # NaN -> 0


PRODUCE_KINDS = frozenset({"spot", "slot", "order"})


def produce_round_share(game) -> float:
    """Spot/slot/order rounds over all quiz rounds of a player game (0.0 when unknown). Not item-weighted."""
    if not isinstance(game, dict):
        return 0.0
    kinds = [str((s.get("quiz") or {}).get("kind") or "mcq").lower() for s in game.get("scenes") or []
             if isinstance(s, dict) and isinstance(s.get("quiz"), dict)]
    return sum(1 for k in kinds if k in PRODUCE_KINDS) / len(kinds) if kinds else 0.0


def select(candidates) -> dict:
    """{"winner": id | None, "ranked": [eligible ids, best first], "reasons": {id: why not / "selected"}}.

    A candidate: {"id", "card" (full gate card, doctrine run), "grounding" (0..1), "game" (player JSON)};
    "generation_ratio" may be present and is recorded, but never ranks.
    Eligible = deterministic gates pass AND no mandatory failure AND card overall_pass is literally True."""
    eligible, reasons = [], {}
    for c in candidates or []:
        cid = str((c or {}).get("id"))
        card = (c or {}).get("card")
        fails = mandatory_failures(card)
        if not deterministic_pass(card):
            reasons[cid] = "deterministic gates failed: " + ", ".join(failing(card, DETERMINISTIC_GATES))
        elif fails:
            reasons[cid] = "gates failed: " + ", ".join(fails)
        elif card.get("overall_pass") is not True:
            reasons[cid] = "card overall_pass is not True"
        else:
            eligible.append(c)
    eligible.sort(key=lambda c: (tuple(-x for x in doctrine_score(c["card"])), -_num(c.get("grounding")),
                                 -produce_round_share(c.get("game")), str(c.get("id"))))
    ranked = [str(c.get("id")) for c in eligible]
    for i, cid in enumerate(ranked):
        reasons[cid] = "selected" if i == 0 else f"eligible, ranked {i + 1}"
    return {"winner": ranked[0] if ranked else None, "ranked": ranked, "reasons": reasons}


def yield_ok(results) -> float:
    """Share of requests with any passing draft (rung 2's real metric; the surfaced pass rate is ~100% by
    construction). `results` = list of select() outputs."""
    results = list(results or [])
    return sum(1 for r in results if r.get("winner")) / len(results) if results else 0.0
