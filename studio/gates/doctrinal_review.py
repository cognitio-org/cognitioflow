"""Doctrinal review gate.

Pass 1 (support): the reviewer checks that the generated text (question, correct
answer, teaching, IRAC rule) is supported by the authoritative SOURCE.
Pass 2 (distractors): each deliberately wrong option is checked separately: it
must be wrong *under the source* for the reason its teaching gives, and must not
state false law as if it were true outside the mistake it models.

Quoted-support rule: with ``require_quotes=True`` (always on for pass 2, and what
the docket adapter uses for pass 1), an ``ok: true`` verdict must carry
``quotes``: exact substrings of the SOURCE (whitespace-normalised) that Python
verifies here. A missing, too-short or unverifiable quote turns the verdict into
a failure, so a same-family reviewer cannot ratify a hallucination without
pointing at the source. Every path fails closed.
"""
import json
import re
from dataclasses import dataclass, field

MIN_QUOTE_CHARS = 12  # after whitespace normalisation; stops "the"/"a" from "verifying"


@dataclass
class DoctrineVerdict:
    ok: bool
    issues: list[str]
    raw: str
    quotes: list[str] = field(default_factory=list)


def build_prompt(source_text: str, generated_text: str) -> str:
    return f"""Compare the GENERATED legal content against the authoritative SOURCE passage. Check that the generated text does not misstate or distort the doctrine in the source, including by inventing a legal rule, misstating an element, or reversing a rule.

SOURCE:
{source_text}

GENERATED:
{generated_text}

Return STRICT JSON only, in this format:
{{"ok": <bool>, "issues": [<short strings>], "quotes": [<exact substrings copied from SOURCE>]}}
Set "ok" to false if the generated text states a legal rule, element, or consequence that the source does not support. Otherwise set "ok" to true and "issues" to an empty list.
When "ok" is true, "quotes" MUST list the exact SOURCE passages (copied verbatim, at least a few words each) that support every legal proposition in the generated text. Do not paraphrase quotes.
"""


def build_distractor_prompt(source_text: str, question: str, option_text: str, teaching: str) -> str:
    """Pass 2: review one deliberately WRONG option (a distractor) against the source."""
    return f"""You are reviewing a DISTRACTOR: an answer option that is deliberately WRONG in a law revision game. Being wrong is intended. Judge it against the authoritative SOURCE passage.

SOURCE:
{source_text}

QUESTION:
{question}

DISTRACTOR (the wrong option, including any story text):
{option_text}

TEACHING (the explanation shown to the player of why this option is wrong):
{teaching}

Check two things:
1. Is the distractor wrong UNDER THE SOURCE, for the reason the teaching gives? The teaching must itself be supported by the source.
2. Does any of the distractor's text state false law AS IF IT WERE TRUE, outside the specific mistake it models (for example, a narrator line asserting an invented rule as fact)?

Return STRICT JSON only, in this format:
{{"ok": <bool>, "issues": [<short strings>], "quotes": [<exact substrings copied from SOURCE>]}}
Set "ok" to true only if the distractor is wrong for the reason the teaching gives AND it states no false law as fact. Otherwise set "ok" to false and describe each problem in "issues".
When "ok" is true, "quotes" MUST list the exact SOURCE passages (copied verbatim, at least a few words each) that show why the distractor is wrong. Do not paraphrase quotes.
"""


def _unparseable(raw: str) -> DoctrineVerdict:
    return DoctrineVerdict(ok=False, issues=["unparseable reviewer output"], raw=raw)


def parse_verdict(raw: str) -> DoctrineVerdict:
    """Extract and validate the first JSON object, failing closed if it is unreadable.

    ``quotes`` is optional here (legacy reviewers omit it); if present it must be a
    list of strings. Quote verification happens in ``apply_quote_rule``.
    """
    if not isinstance(raw, str):
        return _unparseable(str(raw))
    json_match = re.search(
        r'\{(?:[^{}"]|"(?:\\.|[^"\\])*")*\}',
        raw,
        re.DOTALL,
    )
    if not json_match:
        return _unparseable(raw)

    try:
        data = json.loads(json_match.group(0), strict=False)  # tolerate raw newlines in verbatim quotes
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("ok"), bool)
            or not isinstance(data.get("issues"), list)
            or not all(isinstance(issue, str) for issue in data["issues"])
        ):
            raise ValueError("invalid reviewer verdict")
        quotes = data.get("quotes", [])
        if not isinstance(quotes, list) or not all(isinstance(q, str) for q in quotes):
            raise ValueError("invalid reviewer quotes")
        return DoctrineVerdict(ok=data["ok"], issues=data["issues"], raw=raw, quotes=quotes)
    except (json.JSONDecodeError, ValueError):
        return _unparseable(raw)


def _norm(text: str) -> str:
    return " ".join(text.split())


def unverified_quotes(source_text: str, quotes: list[str]) -> list[str]:
    """Return every quote that is not a whitespace-normalised substring of the source
    (or is shorter than MIN_QUOTE_CHARS after normalisation)."""
    src = _norm(source_text)
    bad = []
    for q in quotes:
        nq = _norm(q)
        if len(nq) < MIN_QUOTE_CHARS or nq not in src:
            bad.append(q)
    return bad


def apply_quote_rule(verdict: DoctrineVerdict, source_text: str) -> DoctrineVerdict:
    """Fail an ``ok: true`` verdict that lacks verifiable source quotes.

    ``ok: false`` verdicts are returned unchanged (already failing).
    """
    if not verdict.ok:
        return verdict
    if not verdict.quotes:
        return DoctrineVerdict(ok=False, issues=["no supporting source quotes"],
                               raw=verdict.raw, quotes=verdict.quotes)
    bad = unverified_quotes(source_text, verdict.quotes)
    if bad:
        shown = "; ".join(repr(q[:80]) for q in bad[:3])
        return DoctrineVerdict(ok=False, issues=[f"unverifiable source quote(s): {shown}"],
                               raw=verdict.raw, quotes=verdict.quotes)
    return verdict


def review_doctrine(source_text: str, generated_text: str, reviewer, *, require_quotes: bool = False) -> DoctrineVerdict:
    """Pass 1: review generated text against the source using the injected reviewer callable.

    ``require_quotes=False`` keeps the Phase-1 harness behaviour; the docket adapter
    passes ``True`` so an unquoted or misquoted ``ok: true`` fails closed.
    """
    raw = reviewer(build_prompt(source_text, generated_text))
    verdict = parse_verdict(raw)
    return apply_quote_rule(verdict, source_text) if require_quotes else verdict


def review_distractor(source_text: str, question: str, option_text: str, teaching: str, reviewer) -> DoctrineVerdict:
    """Pass 2: review one wrong option. Quotes are always required."""
    raw = reviewer(build_distractor_prompt(source_text, question, option_text, teaching))
    return apply_quote_rule(parse_verdict(raw), source_text)
