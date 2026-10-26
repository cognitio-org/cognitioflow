"""What deserves Matej's attention, and what deserves a warning label.

A harvester that ranks by recency is a news feed. The difference between a news feed and a
research agent is that the agent knows *why* a result might be wrong, and says so on the face
of the record.

Two ideas do the work here.

**Authority.** CognitioFlow already ranks its course material (annotated WG notes > lecture >
slides > Schutze) and labels anything outside the ticked files `[OUTSIDE FILES]`. The same
discipline applies to outside research: a judgment and a preprint are not the same kind of
thing, and a brief that presents them identically is misleading even when every fact in it is
true. `Source.authority` carries that rank; the flags below carry the caveats.

**Falsification beats discovery.** On the quant track especially, the finding that a published
predictor failed out of sample is worth more than the original paper. McLean and Pontiff
measured roughly a 26% decay in published anomaly returns between a sample's end and
publication, and a further 32% after — Hou, Xue and Zhang could not replicate most of the
literature at all, and Harvey, Liu and Zhu argued the t-statistic hurdle for a *new* factor
should be about 3.0 rather than 2.0 precisely because so many were tested. So `REPLICATION` and
`RETRACTED` raise a record's score rather than lowering it. Knowing a signal is dead is the
tradeable fact.
"""

import datetime as dt
import re

# Phrases that mean "this paper is checking someone else's homework" — the highest-value shape
# of result on the quant track.
_REPLICATION = (
    "replicat", "out-of-sample", "out of sample", "fails to", "failure to",
    "factor zoo", "multiple testing", "p-hacking", "data snooping", "publication bias",
    "non-replicab", "irreproducib", "overfitting", "deflated sharpe",
)

_RETRACTION = ("retract", "withdrawn", "expression of concern", "corrigendum")

# A performance claim with none of this vocabulary anywhere near it is a red flag, not a result.
_OOS_VOCAB = (
    "out-of-sample", "out of sample", "holdout", "hold-out", "walk-forward",
    "cross-validation", "cross validation", "validation set", "test set", "purged",
)
_PERF_CLAIM = (
    "sharpe", "alpha", "abnormal return", "outperform", "excess return",
    "annualized return", "annualised return", "predictive accuracy", "profitab",
)

# Track watchlists. These are the standing questions the agent is reading *for*.
WATCH = {
    "quant": (
        "asset pricing", "cross-section", "momentum", "value premium", "factor",
        "market microstructure", "liquidity", "limit order book", "volatility",
        "term structure", "monetary policy", "transaction cost", "market impact",
        "regime", "tail risk", "machine learning",
    ),
    "legal": (
        "due diligence", "beneficial owner", "sanctions", "anti-money laundering",
        "disclosure", "free movement", "internal market", "proportionality",
        "competition", "state aid", "data protection", "procurement",
        "corporate governance", "securities fraud", "compliance",
    ),
    "system": (
        "spacing", "retrieval practice", "testing effect", "interleav",
        "desirable difficult", "forgetting curve", "evaluation", "judge",
        "rubric", "retrieval-augmented", "benchmark", "inter-rater",
    ),
}

# Where the two halves of the ask actually meet. A record touching these is worth more than a
# record on either track alone, because one read serves both the study and the side hustle.
_CROSSOVER = (
    "disclosure", "filing", "securities regulation", "insider", "market abuse",
    "enforcement", "prospectus", "financial reporting", "audit", "fraud detection",
)

# The course Matej is actually sitting exams in. Research that lands here is study time and
# billable time at once.
_COURSE = (
    "free movement of goods", "article 34", "article 36", "tfeu", "internal market",
    "customs union", "property law", "ownership", "possession", "transfer of property",
    "security right", "co-ownership", "court of justice", "preliminary reference",
)


def _text(record) -> str:
    return f"{record.title} {record.abstract} {record.venue}".lower()


def _any(haystack: str, needles) -> bool:
    return any(n in haystack for n in needles)


def flags_for(record, today=None) -> tuple:
    """Warning and merit labels, decided from the record's own text."""
    text = _text(record)
    out = []

    if _any(text, _RETRACTION):
        out.append("RETRACTED")
    if _any(text, _REPLICATION):
        out.append("REPLICATION")
    if record.authority >= 5:
        out.append("PREPRINT")

    # A performance claim that never mentions holding data back.
    if _any(text, _PERF_CLAIM) and not _any(text, _OOS_VOCAB):
        out.append("NO-OOS")

    # Claims about many signals at once, without any nod to the multiple-testing problem.
    if re.search(r"\b\d{2,4}\s+(factors|anomalies|predictors|signals|strategies)\b", text) \
            and "multiple testing" not in text and "false discovery" not in text:
        out.append("MULTI-TEST")

    if _any(text, _CROSSOVER):
        out.append("CROSSOVER")
    if _any(text, _COURSE):
        out.append("COURSE")

    if record.date and today:
        age = (today - _parse(record.date)).days if _parse(record.date) else None
        if age is not None and age <= 7:
            out.append("NEW")

    return tuple(out)


def _parse(iso: str):
    try:
        return dt.date.fromisoformat(iso)
    except (ValueError, TypeError):
        return None


def score(record, today=None) -> tuple:
    """Return `(score, flags)`. Higher is more worth the next ten minutes.

    The weights are deliberately blunt and readable. A scoring function nobody can argue with
    is a scoring function nobody checks.
    """
    today = today or dt.date.today()
    flags = flags_for(record, today)
    text = _text(record)

    # Authority: 1 (binding/primary) scores 5, 5 (un-reviewed) scores 1.
    value = float(6 - record.authority)

    # Recency, tapering over a quarter. Undated material ranks last, on purpose.
    published = _parse(record.date)
    if published:
        age = max((today - published).days, 0)
        value += max(0.0, 3.0 - (age / 30.0))
    else:
        value -= 1.0

    # Standing questions on this track.
    hits = sum(1 for term in WATCH.get(record.track, ()) if term in text)
    value += min(hits, 4) * 0.75

    # Merit and warning adjustments.
    if "REPLICATION" in flags:
        value += 3.0      # checking someone's homework is the most useful thing a paper can do
    if "RETRACTED" in flags:
        value += 2.5      # must be seen, precisely because it is wrong
    if "CROSSOVER" in flags:
        value += 1.5      # one read, two uses
    if "COURSE" in flags:
        value += 1.5      # exam material and billable material at once
    if "NO-OOS" in flags:
        value -= 2.0      # a performance claim with no holdout is an advertisement
    if "MULTI-TEST" in flags:
        value -= 1.5
    if "PREPRINT" in flags:
        value -= 0.5

    return round(max(value, 0.0), 2), flags


def rank(records, today=None, limit=0) -> list:
    """Score every record in place, then sort. Ties break towards the newer thing."""
    today = today or dt.date.today()
    for record in records:
        record.score, record.flags = score(record, today)
    ordered = sorted(records, key=lambda r: (-r.score, r.date or "", r.title), reverse=False)
    ordered = sorted(ordered, key=lambda r: (-r.score, _sort_date(r)))
    return ordered[:limit] if limit else ordered


def _sort_date(record):
    """Newer first within a score band; undated last."""
    return (0, "") if not record.date else (-1, _negate(record.date))


def _negate(iso: str) -> str:
    """Invert an ISO date so plain ascending sort puts the newest first."""
    return "".join(chr(ord("9") - int(c)) if c.isdigit() else c for c in iso)
