"""The printed pack (Phase 18d): what a course's notes already say, laid out for paper. Pure, no database, no model.

Decided with Matej (Phase 18 brief, decision 7, signed off 2026-09-30): the pack is for revising at home and never
goes into the exam. A page per syllabus week - the rule (the note's opening box), the outline, the leading cases
in the order they were decided with the note each came from, and the exam method's steps where the week's notes
work through them - and a sheet of tab labels: an article number and a one-word heading, nothing that would count
as an annotation in the statute book.
"""
import re
from collections import Counter, defaultdict

import essay

RULE_CHARS = 900          # the opening box, as written; a box longer than this is cut at a sentence
OUTLINE = 10              # section headings shown per week
CASES = 14                # leading cases per week
METHOD_HITS = 2           # a week's notes must name at least two of the method's moves before the steps print

_H1 = re.compile(r"^#\s+(.+)$", re.M)
_H2 = re.compile(r"^##\s+(.+)$", re.M)
_QUOTE = re.compile(r"(?:^>.*(?:\n|$))+", re.M)
_MOVES = {"applicability": r"applicab", "restriction": r"restrict|\bscope\b", "justification": r"justif|proportional"}

# Article references, by instrument. Each yields (instrument, number) and prints as "Art 34 TFEU", "3:84 BW",
# "VIII.-2:101 DCFR". Treaty numbers are kept only when an instrument is named next to them: a bare "Art 5" says
# nothing on a tab.
_ARTICLES = [
    (re.compile(r"\bArt(?:icle|s?\.)?s?\s+(\d{1,3}[a-z]?)(?:\(\d+\))?\s+(TFEU|TEU|ECHR)\b"), lambda m: (m.group(2), m.group(1))),
    (re.compile(r"\b(?:Art(?:icle|\.)?\s+)?(\d{1,2}:\d{1,3}[a-z]?)\s+(?:Dutch\s+)?(BW|DCC)\b"), lambda m: ("BW", m.group(1))),
    (re.compile(r"\b([IVX]{1,4}\.?[-–]\d{1,2}:\d{3}[a-z]?)\b"), lambda m: ("DCFR", m.group(1).replace("–", "-"))),
    (re.compile(r"\bArt(?:icle|\.)?\s+(\d{1,3})\s+(?:of\s+the\s+)?(Charter|EUCFR)\b"), lambda m: ("Charter", m.group(1))),
]
_HEAD_STOP = set("week lecture lectures notes note working group brief answered the and of in on to a an for eu law "
                 "free movement principles general concepts part i ii iii q1 q2 q12 against acts complete exam hooks traps "
                 "case cases rule rules test tests key overview summary article articles national provisions reference "
                 "index machine clause by with from what how when where why table map".split())


def _week_word(title: str) -> str:
    """One word for a tab, from a heading: "Week 3 — Transfer of goods and ..." gives "Transfer",
    "Free movement of goods" gives "Goods"."""
    after = re.split(r"\s[—–:-]\s|:\s", title, maxsplit=1)[-1]
    for w in re.findall(r"[A-Za-zÀ-ÿ]+", after):
        if w.lower() not in _HEAD_STOP and len(w) > 2:
            return w[:1].upper() + w[1:].lower()
    return ""


_RULE_BOX = re.compile(r"(?i)in one glance|\*\*frame\b|\bgate\b|\*\*rule\b|the core sequence")
_META = re.compile(r"(?i)\b(?:status|provenance key|engine map|teaching setup|sources?):")


def _rule(body: str) -> str:
    """The note's opening box ("> **In one glance** ...", "> **Frame** Gate ..."), as markdown without the quote
    marks. A box that only describes the note itself (status, provenance key, sources) is passed over."""
    boxes = ["\n".join(line[1:].lstrip() if line.startswith(">") else line for line in m.group(0).rstrip().splitlines())
             for m in _QUOTE.finditer(body or "")]
    boxes = [b for b in boxes if not _META.search(b[:120]) and not b.lstrip().startswith(("✅", "⚠", "**Trap", "**Exam move"))]
    text = next((b for b in boxes if _RULE_BOX.search(b[:80])), boxes[0] if boxes else "")
    if not text:
        return ""
    if len(text) > RULE_CHARS:
        cut = text.rfind(". ", 0, RULE_CHARS)
        text = text[:cut + 1 if cut > RULE_CHARS // 2 else RULE_CHARS].rstrip() + " …"
    return text


_ROMAN = {"I": 1, "V": 5, "X": 10}


def _sort_number(n: str):
    """3:84 -> [0, 3, 84]; VIII.-2:101 -> [8, 2, 101]: DCFR books in book order, then chapter and article."""
    m = re.match(r"([IVX]+)\.?-", n)
    book = 0
    if m:
        vals = [_ROMAN[c] for c in m.group(1)]
        book = sum(-v if i + 1 < len(vals) and v < vals[i + 1] else v for i, v in enumerate(vals))
    return [book] + [int(p) for p in re.findall(r"\d+", n[m.end():] if m else n)]


_ADJECTIVES = set("basic new adequate future unspecified general specific successive initial subsequent other "
                  "certain particular special main further".split())


def _index_word(heading: str) -> str:
    """One word from an article-index heading: "Basic requirements" -> "Requirements", "Competition between
    successive assignees" -> "Competition"."""
    if re.match(r"(?i)\s*good[- ]faith\b", heading or ""):
        return "Good-faith"
    for w in re.findall(r"[A-Za-zÀ-ÿ-]+", heading or ""):
        lw = w.lower().strip("-")
        if lw not in _HEAD_STOP and lw not in _ADJECTIVES and len(lw) > 2:
            return lw[:1].upper() + lw[1:]
    return ""


def _article_index(notes) -> dict:
    """{article number: heading} from any note table with an Article column and a Heading column - his own
    article index. Bold, "Art", "art." and the instrument are stripped so "**III.-5:104**" and "3:84 BW" match."""
    out = {}
    for n in notes:
        lines = (n.get("body") or "").splitlines()
        for i in range(len(lines) - 1):
            if not (lines[i].lstrip().startswith("|") and re.match(r"^\s*\|?\s*:?-+", lines[i + 1])): continue
            head = [h.strip().lower() for h in lines[i].strip().strip("|").split("|")]
            ai = next((k for k, h in enumerate(head) if h.startswith("art")), None)
            hi = next((k for k, h in enumerate(head) if h.startswith("heading") or h == "topic"), None)
            if ai is None or hi is None: continue
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                row = [c.strip(" *") for c in lines[j].strip().strip("|").split("|")]; j += 1
                if len(row) != len(head): continue
                num = re.sub(r"(?i)^art(?:icle|\.)?\s*|\s*(?:BW|DCFR|TFEU|TEU|ECHR|Charter)$", "", row[ai]).strip(" *").replace("–", "-")
                word = _index_word(row[hi])
                if num and word: out.setdefault(num, word)
    return out


def build(weeks: dict, reference: list, cases: list, method: bool = True) -> dict:
    """weeks: {week: [note, ...]} (as countdown.sort_notes gives them); reference: course-wide notes;
    cases: the case index (name, cite, year, notes [{id, title}]). Returns {"topics": [...], "tabs": [...]}."""
    topics, words = [], {}
    for week in sorted(weeks, key=lambda w: (not str(w).isdigit(), int(w) if str(w).isdigit() else 0, str(w))):
        notes = sorted(weeks[week], key=lambda n: n["title"])
        ids = {n["id"] for n in notes}
        body = "\n\n".join(n.get("body") or "" for n in notes)
        title = re.sub(r"^\s*(?:Week|Wk)\s*0?\d+\s*[—–:-]\s*", "", notes[0]["title"]).strip() if notes else f"Week {week}"
        rule = next((r for r in (_rule(n.get("body")) for n in notes) if r), "")
        outline = [re.sub(r"^\d+[.)]\s*", "", h.strip(" #*")) for n in notes for h in _H2.findall(n.get("body") or "")][:OUTLINE]
        own = [c for c in cases if any(x["id"] in ids for x in c.get("notes", []))]
        own.sort(key=lambda c: (c.get("year") is None, c.get("year") or 0, c["name"].casefold()))
        moves = [k for k, rx in _MOVES.items() if re.search(rx, body, re.I)]
        topics.append({
            "week": str(week), "title": title, "rule": rule, "outline": outline,
            "cases": [{"name": re.sub(r"\*|,\s*(?:CJEU|ECJ|ECtHR)$|,?\s*at\s*\[?paras?\b.*$", "", c["name"]).strip(" ,"), "cite": c.get("cite") or "", "year": c.get("year"),
                       "note": next(x["title"] for x in c["notes"] if x["id"] in ids)} for c in own[:CASES]],
            "more_cases": max(0, len(own) - CASES),
            "method": [label for _, label in essay.LIMBS] if method and len(moves) >= METHOD_HITS else [],
        })
        words[str(week)] = _week_word(notes[0]["title"]) if notes else ""
    # Each tab's word comes from his own article index where it has the article; otherwise from the title of the
    # week that cites it most; otherwise none - a blank tab is better than a wrong one.
    index = _article_index(list(reference) + [n for ns in weeks.values() for n in ns])
    found = defaultdict(Counter)
    for week, notes in list(weeks.items()) + [(None, reference)]:
        for n in notes:
            for rx, key in _ARTICLES:
                for m in rx.finditer(n.get("body") or ""):
                    found[key(m)][str(week) if week is not None else ""] += 1
    tabs = []
    for (instrument, number), by_week in found.items():
        weekly = [(c, w) for w, c in by_week.items() if w]
        heading = index.get(number) or (words.get(max(weekly)[1], "") if weekly else "")
        tabs.append({"instrument": instrument, "number": number,
                     "label": f"{number} {instrument}" if instrument in ("BW", "DCFR") else f"Art {number} {instrument}",
                     "heading": heading})
    order = {"TFEU": 0, "TEU": 1, "Charter": 2, "ECHR": 3, "BW": 4, "DCFR": 5}
    tabs.sort(key=lambda t: (order.get(t["instrument"], 9), _sort_number(t["number"]), t["number"]))
    return {"topics": topics, "tabs": tabs}
