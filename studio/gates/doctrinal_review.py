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

Thinking models: ``<think>...</think>`` reasoning (and anything before an orphan
``</think>``) is dropped before parsing, so a draft verdict inside the reasoning can
never win; an unclosed ``<think>`` drops the rest of the output (fail closed).
An ``ok: true`` verdict that still lists issues is contradictory and fails.
Quote checks ignore case and typographic quote/dash variants (curly quotes to
straight, en/em dash to hyphen); nothing else is equated.

Source headers: the docket adapter puts each cited file under a ``[Sn] file`` header
line. Those lines are the adapter's own words, not the source, so quotes are checked
against the source BODIES only (header lines removed, each body checked on its own so
a quote cannot stitch two files together), and a quote must carry at least one
alphabetic word of 4+ characters that is not a header word. ``split_sources`` lets a
caller supply its own header split.

Several verdicts: only top-level JSON objects count (a verdict nested inside another
object is rejected). If more than one top-level verdict remains after the reasoning
is stripped, they must agree on ``ok``, else the review fails closed; the LAST one wins.
"""
import json
import re
from dataclasses import dataclass, field

MIN_QUOTE_CHARS = 12  # after normalisation (see _norm); stops "the"/"a" from "verifying"
MIN_WORD_CHARS = 4    # a quote needs one alphabetic word this long that is not a header word

# A "[S1] week3-lecture-notes.pdf" header line, as docket_adapter.cited_source_text writes it.
HEADER_LINE = re.compile(r"^[ \t]*\[S\d+\][^\n]*$", re.MULTILINE)
_WORD = re.compile(r"[^\W\d_]+")


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


_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE = re.compile(r"</think\s*>", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think\b[^>]*>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove model reasoning so only the final answer is parsed.

    1. drop every complete ``<think>...</think>`` block;
    2. drop everything up to and including the last remaining (orphan) ``</think>``;
    3. drop everything from an unclosed ``<think>`` to the end.
    """
    text = _THINK_BLOCK.sub("", text)
    closes = list(_THINK_CLOSE.finditer(text))
    if closes:
        text = text[closes[-1].end():]
    opened = _THINK_OPEN.search(text)
    if opened:
        text = text[:opened.start()]
    return text


def _unparseable(raw: str) -> DoctrineVerdict:
    return DoctrineVerdict(ok=False, issues=["unparseable reviewer output"], raw=raw)


def _top_level_objects(text: str) -> tuple[list[str], str]:
    """Every top-level ``{...}`` span in ``text``, string-aware, plus any unclosed tail.

    Braces inside JSON strings do not count; quote characters outside any object (prose)
    are ignored. A ``{`` that is never closed returns its tail as the second value.
    """
    spans, depth, start, in_str, esc = [], 0, 0, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"' and depth:
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                spans.append(text[start:i + 1])
    return spans, (text[start:] if depth else "")


_OK_KEY = re.compile(r'"ok"\s*:')


def _verdict(data: dict, raw: str) -> DoctrineVerdict:
    """Validate one parsed verdict dict; raise ValueError if its shape is wrong."""
    if (
        not isinstance(data.get("ok"), bool)
        or not isinstance(data.get("issues"), list)
        or not all(isinstance(issue, str) for issue in data["issues"])
    ):
        raise ValueError("invalid reviewer verdict")
    quotes = data.get("quotes", [])
    if not isinstance(quotes, list) or not all(isinstance(q, str) for q in quotes):
        raise ValueError("invalid reviewer quotes")
    ok = data["ok"] and not data["issues"]  # ok:true + issues is contradictory: fail closed
    return DoctrineVerdict(ok=ok, issues=data["issues"], raw=raw, quotes=quotes)


def parse_verdict(raw: str) -> DoctrineVerdict:
    """Extract and validate the reviewer's verdict after its reasoning, failing closed.

    Only TOP-LEVEL JSON objects with an ``"ok"`` key are verdicts; one nested inside
    another object (``{"verdict": {"ok": true}}``) is not, and alone is unparseable.
    A top-level object that mentions ``"ok"`` but does not parse fails closed, as does an
    unclosed one. With several verdicts (``Draft: {...} Final: {...}``) every one must be
    well-formed and they must agree on ``ok``, else the result fails closed; the LAST is
    returned. ``quotes`` is optional here (legacy reviewers omit it); if present it must
    be a list of strings. Quote verification happens in ``apply_quote_rule``.
    ``ok: true`` with a non-empty ``issues`` list is treated as a failure.
    ``raw`` on the returned verdict is always the untouched reviewer output.
    """
    if not isinstance(raw, str):
        return _unparseable(str(raw))
    spans, tail = _top_level_objects(strip_reasoning(raw))
    if _OK_KEY.search(tail):
        return _unparseable(raw)  # a verdict that never closes: cannot know what it said
    verdicts = []
    try:
        for span in spans:
            try:
                data = json.loads(span, strict=False)  # tolerate raw newlines in verbatim quotes
            except json.JSONDecodeError:
                if _OK_KEY.search(span):
                    raise ValueError("unreadable reviewer verdict")
                continue  # prose in braces, not a verdict
            if isinstance(data, dict) and "ok" in data:
                verdicts.append(_verdict(data, raw))
    except ValueError:
        return _unparseable(raw)
    if not verdicts:
        return _unparseable(raw)
    if len({v.ok for v in verdicts}) > 1:
        return DoctrineVerdict(ok=False, issues=["conflicting reviewer verdicts"], raw=raw)
    return verdicts[-1]


_TYPOGRAPHY = str.maketrans({
    "\u2018": "'", "\u2019": "'",   # curly single quotes
    "\u201c": '"', "\u201d": '"',   # curly double quotes
    "\u2013": "-", "\u2014": "-",   # en dash, em dash
})


def _norm(text: str) -> str:
    """Whitespace-collapse, straighten curly quotes, en/em dash to hyphen, casefold."""
    return " ".join(text.translate(_TYPOGRAPHY).split()).casefold()


def split_source_headers(source_text: str) -> tuple[list[str], list[str]]:
    """Default header split: (source bodies, header lines) around ``[Sn] file`` lines.

    Each body is the text between two header lines (or the ends of the source)."""
    headers = [m.group(0) for m in HEADER_LINE.finditer(source_text)]
    return HEADER_LINE.split(source_text), headers


def unverified_quotes(source_text: str, quotes: list[str], *, split_sources=None) -> list[str]:
    """Return every quote that does not verify against the source.

    A quote verifies only if, after normalisation (see ``_norm``), it is at least
    MIN_QUOTE_CHARS long, is a substring of ONE source body (header lines removed, see
    ``split_source_headers``; ``split_sources`` overrides it with the same return shape),
    and contains an alphabetic word of MIN_WORD_CHARS+ characters that is not a word of
    any header line.
    """
    bodies, headers = (split_sources or split_source_headers)(source_text)
    bodies = [_norm(b) for b in bodies]
    header_words = {w for h in headers for w in _WORD.findall(_norm(h))}
    bad = []
    for q in quotes:
        nq = _norm(q)
        real_word = any(len(w) >= MIN_WORD_CHARS and w not in header_words for w in _WORD.findall(nq))
        if len(nq) < MIN_QUOTE_CHARS or not real_word or not any(nq in b for b in bodies):
            bad.append(q)
    return bad


def apply_quote_rule(verdict: DoctrineVerdict, source_text: str, *, split_sources=None) -> DoctrineVerdict:
    """Fail an ``ok: true`` verdict that lacks verifiable source quotes.

    ``ok: false`` verdicts are returned unchanged (already failing).
    ``split_sources`` is passed to ``unverified_quotes``.
    """
    if not verdict.ok:
        return verdict
    if not verdict.quotes:
        return DoctrineVerdict(ok=False, issues=["no supporting source quotes"],
                               raw=verdict.raw, quotes=verdict.quotes)
    bad = unverified_quotes(source_text, verdict.quotes, split_sources=split_sources)
    if bad:
        shown = "; ".join(repr(q[:80]) for q in bad[:3])
        return DoctrineVerdict(ok=False, issues=[f"unverifiable source quote(s): {shown}"],
                               raw=verdict.raw, quotes=verdict.quotes)
    return verdict


def review_doctrine(source_text: str, generated_text: str, reviewer, *, require_quotes: bool = False,
                    split_sources=None) -> DoctrineVerdict:
    """Pass 1: review generated text against the source using the injected reviewer callable.

    ``require_quotes=False`` is the legacy no-quote behaviour (kept for old callers);
    the harness and the docket adapter pass ``True`` so an unquoted or misquoted
    ``ok: true`` fails closed.
    """
    raw = reviewer(build_prompt(source_text, generated_text))
    verdict = parse_verdict(raw)
    if not require_quotes:
        return verdict
    return apply_quote_rule(verdict, source_text, split_sources=split_sources)


def review_distractor(source_text: str, question: str, option_text: str, teaching: str, reviewer, *,
                      split_sources=None) -> DoctrineVerdict:
    """Pass 2: review one wrong option. Quotes are always required."""
    raw = reviewer(build_distractor_prompt(source_text, question, option_text, teaching))
    return apply_quote_rule(parse_verdict(raw), source_text, split_sources=split_sources)
