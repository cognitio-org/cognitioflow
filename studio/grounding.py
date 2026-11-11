"""CF Game Studio: per-claim grounding check (model-quality plan, rung 0 item 7).

Every `checks[]` entry the writer emits carries a verbatim `quote` from one of the source keys it cites. Python,
not a model, verifies it: the quote must verify (doctrinal_review.unverified_quotes: normalised substring, long
enough, with a real word) against the text of a cited key. A failure becomes a repair-round problem for the
writer; the grounding share is a selection tie-break in best-of-N and a metric in the eval.

Stdlib only. Reuses the doctrine gate's normaliser so the writer and the gate agree on what "verbatim" means.
"""
from __future__ import annotations

import re

from studio import docket_adapter

_KEY = re.compile(r"[A-Z][A-Z0-9]{0,5}")
# The doctrine verifier accepts any 12-character fragment with one 4+ letter word ("the State is"), which any
# claim could "cite". A claim's support must be a real sentence fragment: at least MIN_QUOTE_WORDS words, and no
# quote may be reused for a second claim (adversarial review 2026-11-11).
MIN_QUOTE_WORDS = 6
_WORDS = re.compile(r"[^\W_]+")


def _dr():
    return docket_adapter._gates().doctrinal_review


def _key(c) -> str:
    s = str(c or "").strip().strip("[]")
    return s.split()[0] if s else ""


def check_problems(checks, keyed: dict, min_checks: int = 1) -> list:
    """Short sentences, one per check whose quote is missing, too short, reused, or not found in a cited source,
    plus one if there are fewer than `min_checks` checks. Empty = grounded."""
    dr, bad, seen = _dr(), [], set()
    if not isinstance(checks, list) or not checks:
        return ["The game has no checks: list each legal claim with its cites and an exact source quote."]
    if len(checks) < max(1, int(min_checks)):
        bad.append(f"The game has {len(checks)} checks; give at least {int(min_checks)} (one or more per round), "
                   f"each with its own exact source quote.")
    for i, c in enumerate(checks, 1):
        if not isinstance(c, dict):
            bad.append(f"check {i} is not an object.")
            continue
        quote = str(c.get("quote") or "").strip()
        keys = [k for k in (_key(x) for x in (c.get("cites") or [])) if _KEY.fullmatch(k or "")]
        if not quote:
            bad.append(f"check {i} has no quote: copy one sentence exactly from the source it cites.")
            continue
        if not keys:
            bad.append(f"check {i} cites no source key.")
            continue
        if len(_WORDS.findall(quote)) < MIN_QUOTE_WORDS:
            bad.append(f"check {i}: the quote {quote[:80]!r} is too short; copy a whole sentence (at least "
                       f"{MIN_QUOTE_WORDS} words) that states the claim.")
            continue
        norm = dr._norm(quote)
        if norm in seen:
            bad.append(f"check {i} reuses the quote of an earlier check; each claim needs its own support.")
            continue
        texts = [str((keyed.get(k) or {}).get("text") or "") for k in keys]
        if not any(t and not dr.unverified_quotes(t, [quote], split_sources=lambda s: ([s], [])) for t in texts):
            bad.append(f"check {i}: the quote {quote[:80]!r} is not in {', '.join(keys)}; copy it word for word "
                       f"from the source, or drop the claim.")
        else:
            seen.add(norm)                         # only a verified quote counts as used
    return bad


def grounding_share(checks, keyed: dict) -> float:
    """Share of checks whose quote verifies against a cited key (0.0 when there are no checks)."""
    if not isinstance(checks, list) or not checks:
        return 0.0
    failed = len(check_problems(checks, keyed))     # min_checks=1: only per-check problems count here
    return max(0.0, (len(checks) - failed) / len(checks))
