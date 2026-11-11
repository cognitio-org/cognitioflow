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


def _dr():
    return docket_adapter._gates().doctrinal_review


def _key(c) -> str:
    s = str(c or "").strip().strip("[]")
    return s.split()[0] if s else ""


def check_problems(checks, keyed: dict) -> list:
    """Short sentences, one per check whose quote is missing or not found in a cited source. Empty = grounded."""
    dr, bad = _dr(), []
    if not isinstance(checks, list) or not checks:
        return ["The game has no checks: list each legal claim with its cites and an exact source quote."]
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
        texts = [str((keyed.get(k) or {}).get("text") or "") for k in keys]
        if not any(t and not dr.unverified_quotes(t, [quote], split_sources=lambda s: ([s], [])) for t in texts):
            bad.append(f"check {i}: the quote {quote[:80]!r} is not in {', '.join(keys)}; copy it word for word "
                       f"from the source, or drop the claim.")
    return bad


def grounding_share(checks, keyed: dict) -> float:
    """Share of checks whose quote verifies against a cited key (0.0 when there are no checks)."""
    if not isinstance(checks, list) or not checks:
        return 0.0
    failed = len(check_problems(checks, keyed))
    return max(0.0, (len(checks) - failed) / len(checks))
