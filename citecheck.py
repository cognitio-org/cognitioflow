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


# The Treaty itself prints "Article 34", never "Article 34 TFEU", so with the consolidated TFEU ticked "Art 34 TFEU"
# was flagged. A bare "Article 34" answers a cited "Art 34 TFEU" only inside a file whose heading names that Treaty
# (its full title, not "TFEU": a lecture says "Article 56 TFEU" in its first lines) and no other, and only an article
# heading on a line of its own, as the Treaty prints it - never "Article 34 of the Services Directive" or
# "(ex Article 28 TEC)". A lecture that says "Article 34" in a sentence is no proof of which one it means.
_HEAD = 400
_TITLE = {"tfeu": re.compile(r"(?i)treaty\s+on\s+the\s+functioning\s+of\s+the\s+european\s+union"),
          "teu": re.compile(r"(?i)treaty\s+on\s+european\s+union"),
          "charter": re.compile(r"(?i)charter\s+of\s+fundamental\s+rights")}
_LINE_START = re.compile(r"(?:^|\n)[ \t]*$")
_LINE_END = re.compile(r"[ \t]*(?:\r?\n|$)")


def _treaty_article(cited: dict, text: str) -> bool:
    """`text` is one file, and it is the text of the instrument `cited` names, printing that article bare."""
    parts = cited["norm"].split()
    if cited["kind"] != "article" or len(parts) != 3 or parts[2] not in _TITLE:
        return False
    head = (text or "")[:_HEAD]
    if [k for k, r in _TITLE.items() if r.search(head)] != [parts[2]]:
        return False
    for m in _ART.finditer(text):
        if m.group(3) or f"art {m.group(1).lower()}{m.group(2) or ''}" != " ".join(parts[:2]):
            continue
        if not (_LINE_START.search(text[max(0, m.start() - 40):m.start()]) or m.start() == 0) or not _LINE_END.match(text, m.end()):
            continue
        return True
    return False


def _bare_case(norm: str, text: str) -> bool:
    """Cases before 1989 have no C- prefix: a reader cites Simmenthal as "Case 106/77", the tutor as "C-106/77"."""
    # Not after a letter and a dash: "T-267/91" is a General Court case, not the Court of Justice's C-267/91.
    if re.search(r"(?<![\d/])(?<![^\W\d_][-‑–])" + re.escape(norm[2:]) + r"(?![\d/])", text):
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
            if not any(_same(c, k) for k in known) and not (c["kind"] == "case" and _bare_case(c["norm"], text))
            and not any(_treaty_article(c, s) for s in sources)]
