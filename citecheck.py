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
    """An article cited without an instrument ("art 267") matches that article in any instrument."""
    if cited["kind"] == known["kind"] == "article" and len(cited["norm"].split()) == 2:
        return cited["norm"] == " ".join(known["norm"].split()[:2])
    return cited["norm"] == known["norm"]


def unverified(answer: str, sources: list[str]) -> list[dict]:
    """The citations in `answer` that appear in none of `sources`."""
    known = [c for s in sources for c in find_citations(s)]
    return [c for c in find_citations(answer) if not any(_same(c, k) for k in known)]
