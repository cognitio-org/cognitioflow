"""CF Game Studio: per-claim grounding check (model-quality plan, rung 0 item 7).

Every `checks[]` entry the writer emits carries a verbatim `quote` from one of the source keys it cites. Python,
not a model, verifies it: the quote must verify (doctrinal_review.unverified_quotes: normalised substring, long
enough, with a real word) against the text of a cited key. A failure becomes a repair-round problem for the
writer; the grounding share is a selection tie-break in best-of-N and a metric in the eval.

WRITER v2 (writer-v2.1+) no longer lets the model type the quote: it cites a numbered sentence id, and
docketgen.numbered_sentence_checks copies that exact source text in as `quote` (and sets `sentence`). This check
then runs unchanged on the copied text, so the 6-word minimum and the reuse / near-duplicate rules still apply; a
check whose id did not resolve is marked `unresolved` and skipped here (its problem is already reported).

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
MAX_WORD_OVERLAP = 0.6   # a quote sharing more of its words than this with an earlier one is the same support
_WORDS = re.compile(r"[^\W_]+")


def _same_support(a: str, b: str) -> bool:
    """True when two normalised quotes are one piece of support: one contains the other, or their word sets
    overlap by more than MAX_WORD_OVERLAP (Jaccard). Stops one sentence being trimmed into several 'checks'."""
    if a in b or b in a:
        return True
    wa, wb = set(_WORDS.findall(a)), set(_WORDS.findall(b))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) > MAX_WORD_OVERLAP


def _dr():
    return docket_adapter._gates().doctrinal_review


def _key(c) -> str:
    """The source key a check cites; a sentence id or range ("S1.18", "S1.18-S1.20") names its source "S1"
    (docketgen._cite_key, the one normaliser the citation check also uses)."""
    return docket_adapter.docketgen._cite_key(c) if str(c or "").strip() else ""


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
        if c.get("unresolved"):
            continue                               # its sentence id did not resolve: that problem is already reported
        sid = str(c.get("sentence") or "").strip()  # WRITER v2: code copied the quote from this sentence id
        quote = str(c.get("quote") or "").strip()
        keys = [k for k in (_key(x) for x in (c.get("cites") or [])) if _KEY.fullmatch(k or "")]
        if not quote:
            bad.append(f"check {i} has no quote: copy one sentence exactly from the source it cites.")
            continue
        if not keys:
            bad.append(f"check {i} cites no source key.")
            continue
        if len(_WORDS.findall(quote)) < MIN_QUOTE_WORDS:
            bad.append(f"check {i}: sentence {sid} ({quote[:80]!r}) is under {MIN_QUOTE_WORDS} words; cite a sentence "
                       f"that states the claim, or a range with its neighbour." if sid else
                       f"check {i}: the quote {quote[:80]!r} is too short; copy a whole sentence (at least "
                       f"{MIN_QUOTE_WORDS} words) that states the claim.")
            continue
        norm = dr._norm(quote)
        if any(_same_support(norm, prev) for prev in seen):
            bad.append(f"check {i}: sentence {sid} says the same as an earlier check's sentence; each claim needs its "
                       f"own support." if sid else
                       f"check {i} reuses (or trims) the quote of an earlier check; each claim needs its own support.")
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
    failed += sum(1 for c in checks if isinstance(c, dict) and c.get("unresolved"))
    return max(0.0, (len(checks) - failed) / len(checks))
