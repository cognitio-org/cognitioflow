"""Find the citations in a tutor answer, so each can be checked against the student's own files.

Only case numbers, ECLIs and article references are recognised; anything else is prose.
"""
import re

_ECLI = re.compile(r"\bECLI:[A-Z]{2}:[A-Z]+:\d{4}:[A-Z0-9.]*[A-Z0-9]", re.IGNORECASE)
_CASE = re.compile(r"\b([CT])[-‑–](\d{1,4}/\d{2,4})\b")
_ART = re.compile(r"(?i)\b(?:art\.?|article|artikel)\s*(\d+(?::\d+)?[a-z]?)(\(\d+\))?(?:\s+(TFEU|TEU|BW|Charter))?(?!\w)")


def find_citations(text: str) -> list[dict]:
    """Every citation in `text`, in order of appearance, one per normalised form."""
    found = []
    for m in _ECLI.finditer(text or ""):
        found.append((m.start(), "ecli", m.group(0), m.group(0).upper()))
    for m in _CASE.finditer(text or ""):
        found.append((m.start(), "case", m.group(0), f"{m.group(1).upper()}-{m.group(2)}"))
    for m in _ART.finditer(text or ""):
        norm = f"art {m.group(1).lower()}{m.group(2) or ''}" + (f" {m.group(3).lower()}" if m.group(3) else "")
        found.append((m.start(), "article", m.group(0), norm))
    out, seen = [], set()
    for _, kind, raw, norm in sorted(found):
        if norm not in seen:
            seen.add(norm)
            out.append({"kind": kind, "raw": raw, "norm": norm})
    return out


def _same(cited: dict, known: dict) -> bool:
    """An article cited without an instrument ("art 267") matches that article in any instrument. And a file that
    names the article without one matches it cited with one: the Treaty itself prints "Article 34", never
    "Article 34 TFEU". Two different instruments still never match."""
    if cited["kind"] == known["kind"] == "article":
        c, k = cited["norm"].split(), known["norm"].split()
        if len(c) == 2:
            return c == k[:2]
        if len(k) == 2:
            return c[:2] == k
    return cited["norm"] == known["norm"]


def _bare_case(norm: str, text: str) -> bool:
    """Cases before 1989 have no C- prefix: a reader cites Simmenthal as "Case 106/77", the tutor as "C-106/77"."""
    if re.search(r"(?<![\d/])" + re.escape(norm[2:]) + r"(?![\d/])", text):
        return True
    # EUR-Lex prints the oldest cases with a dash: "Case 8-74" (Dassonville), "Case 26-62" (Van Gend en Loos).
    # Only after the word "Case", so a page range "8-74" is not taken for one.
    num, year = norm[2:].split("/")
    return re.search(r"(?i)\bcases?\s+" + num + "-" + year + r"(?![\d/-])", text) is not None


def unverified(answer: str, sources: list[str]) -> list[dict]:
    """The citations in `answer` that appear in none of `sources`."""
    known = [c for s in sources for c in find_citations(s)]
    text = "\n".join(sources)
    return [c for c in find_citations(answer)
            if not any(_same(c, k) for k in known) and not (c["kind"] == "case" and _bare_case(c["norm"], text))]
