"""The printed pack (Phase 18d): what a course's notes already say, laid out for paper. Pure, no database, no model.

Decided with Matej (Phase 18 brief, decision 7, signed off 2026-09-30): the pack is for revising at home and never
goes into the exam. A page per syllabus week - the rule (the note's opening box), the outline, the leading cases
in the order they were decided with the note each came from (printed "oldest first", since a year read off a case number is not the judgment year: see normalise_cases), and the exam method's steps where the week's notes
work through them - and a sheet of tab labels: an article number and a one-word heading, nothing that would count
as an annotation in the statute book.
"""
import re
import unicodedata
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


_INDEX_FILLER = {"the", "and", "of", "in", "on", "to", "a", "an", "for", "by", "with", "from", "art", "article", "articles"}


def _index_word(heading: str) -> str:
    """One word from an article-index heading: "Basic requirements" -> "Requirements", "Competition between
    successive assignees" -> "Competition". His heading is his word: when every word is one the week titles skip
    ("Reference", "Rules"), the first of them is still his and prints; a blank tab is only for a blank heading."""
    if re.match(r"(?i)\s*good[- ]faith\b", heading or ""):
        return "Good-faith"
    words = re.findall(r"[A-Za-zÀ-ÿ-]+", heading or "")
    for w in words:
        lw = w.lower().strip("-")
        if lw not in _HEAD_STOP and lw not in _ADJECTIVES and len(lw) > 2:
            return lw[:1].upper() + lw[1:]
    for pool in (_INDEX_FILLER | _ADJECTIVES, _INDEX_FILLER):
        for w in words:
            lw = w.lower().strip("-")
            if lw not in pool and len(lw) > 2:
                return lw[:1].upper() + lw[1:]
    return ""


def _article_index(notes) -> dict:
    """{(instrument, article number): heading, and article number: heading} from any note table with an Article
    column and a Heading column - his own article index. Bold, "Art", "art." and the instrument are stripped so
    "**III.-5:104**" and "3:84 BW" match. A row that names its instrument ("Art 6 TEU") is filed under it only,
    so it never names Art 6 TFEU or Art 6 Charter; a row with a bare number is filed by the number."""
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
                inst = re.search(r"(?i)\s*\b(BW|DCFR|TFEU|TEU|ECHR|Charter)\s*$", row[ai].strip(" *"))
                num = re.sub(r"(?i)^art(?:icle|\.)?\s*|\s*(?:BW|DCFR|TFEU|TEU|ECHR|Charter)$", "", row[ai]).strip(" *").replace("–", "-")
                word = _index_word(row[hi])
                if not (num and word): continue
                if inst:
                    key = {"tfeu": "TFEU", "teu": "TEU", "echr": "ECHR", "charter": "Charter", "bw": "BW", "dcfr": "DCFR"}[inst.group(1).lower()]
                    out.setdefault((key, num), word)
                else:
                    out.setdefault(num, word)
    return out


def build(weeks: dict, reference: list, cases: list, method: bool = True) -> dict:
    """weeks: {week: [note, ...]} (as countdown.sort_notes gives them); reference: course-wide notes;
    cases: the case index (name, cite, year, notes [{id, title}]). Returns {"topics": [...], "tabs": [...]}."""
    topics, words = [], {}
    cases = normalise_cases(_from_notes(cases, {n["id"]: n.get("body") or "" for ns in weeks.values() for n in ns}))
    order = sorted(weeks, key=lambda w: (not str(w).isdigit(), int(w) if str(w).isdigit() else 0, str(w)))
    home = {}                                   # a case belongs to the first week whose notes name it
    for week in order:
        wids = {n["id"] for n in weeks[week]}
        for c in cases:
            if any(x["id"] in wids for x in c.get("notes", [])): home.setdefault(id(c), str(week))
    for week in order:
        notes = sorted(weeks[week], key=lambda n: (_is_wg(n.get("title")), n["title"]))
        doctrine = [n for n in notes if not _is_wg(n.get("title"))] or notes   # a WG-only week still prints
        ids = {n["id"] for n in notes}
        body = "\n\n".join(n.get("body") or "" for n in notes)
        title = _title(doctrine) if notes else f"Week {week}"
        rule = next((r for r in (_rule(n.get("body")) for n in doctrine) if r), "")
        outline = _outline(doctrine, {_name_key(c["name"]) for c in cases}, title)
        own = [c for c in cases if any(x["id"] in ids for x in c.get("notes", []))]
        # A case first met in an earlier week is printed again only where this week works it: a passing "as in
        # Van Gend" (named once, in prose) is listed by name under the table, not as another row.
        recalled = [c for c in own if home.get(id(c)) != str(week) and _passing(c["name"], body)]
        own = [c for c in own if c not in recalled]
        own.sort(key=lambda c: (c.get("year") is None, c.get("year") or 0, c["name"].casefold()))
        moves = [k for k, rx in _MOVES.items() if re.search(rx, body, re.I)]
        topics.append({
            "week": str(week), "title": title, "rule": rule, "outline": outline,
            "cases": [{"name": c["name"], "cite": c.get("cite") or "", "year": c.get("year"),
                       "numbered": bool(c.get("numbered")),
                       "note": _source(next(x["title"] for x in c["notes"] if x["id"] in ids), week, title)} for c in own[:CASES]],
            "more_cases": max(0, len(own) - CASES),
            # an order is claimed only when there is one: a week whose rows carry no year is just 'Leading cases', A-Z
            "cases_heading": "Leading cases, oldest first" if any(c.get("year") for c in own[:CASES]) else "Leading cases",
            "recalled": sorted({c["name"] for c in recalled}, key=str.casefold),
            "method": [label for _, label in essay.LIMBS] if method and len(moves) >= METHOD_HITS else [],
        })
        words[str(week)] = _week_word(title)
    # Each tab's word comes from his own article index where it has the article; otherwise none - a blank tab
    # beats a wrong one (signed off). _HEADINGS is empty until Matej says yes to the proposed article subjects
    # (_HEADINGS_PROPOSED). The older fallback to the first word of the week that cites the article most (18d,
    # 2026-10-01) gave 'Art 107 TFEU - State' and 'Art 34 TFEU - Direct'; it is off (_WEEK_TITLE_TABS) until he
    # decides whether to keep it.
    index = _article_index(list(reference) + [n for ns in weeks.values() for n in ns])
    found = defaultdict(Counter)
    for week, notes in list(weeks.items()) + [(None, reference)]:
        for n in notes:
            for rx, key in _ARTICLES:
                for m in rx.finditer(n.get("body") or ""):
                    found[key(m)][str(week) if week is not None else ""] += 1
    tabs = []
    for (instrument, number), by_week in found.items():
        top = _ARTICLE_MAX.get(instrument)
        if top and not (number[:-1] if number[-1].isalpha() else number).isdigit(): continue
        if top and not 1 <= int(re.match(r"\d+", number).group(0)) <= top: continue   # "Art 168 TEU" does not exist
        weekly = sorted(((c, w) for w, c in by_week.items() if w), reverse=True)
        heading = (index.get((instrument, number)) or index.get(number) or _HEADINGS.get((instrument, number))
                   or (next((words[w] for _, w in weekly if words.get(w)), "") if _WEEK_TITLE_TABS else ""))
        tabs.append({"instrument": instrument, "number": number,
                     "label": f"{number} {instrument}" if instrument in ("BW", "DCFR") else f"Art {number} {instrument}",
                     "heading": heading})
    order = {"TFEU": 0, "TEU": 1, "Charter": 2, "ECHR": 3, "BW": 4, "DCFR": 5}
    tabs.sort(key=lambda t: (order.get(t["instrument"], 9), _sort_number(t["number"]), t["number"]))
    return {"topics": topics, "tabs": tabs}


# ---------------------------------------------------------------- tidying (pitch freeze, 2026-11-14)
# Day-1 judge: the case table printed one case twice under two spellings, doctrines as cases, a year twice, two
# cases in one row; headings shouted; outlines repeated themselves and carried WG answers; some tabs were blank
# or named an article that does not exist. Everything below only reformats what the notes say: no case, case
# number, court letter, year or citation is added that the notes do not carry (follow-up to #224).

_ARTICLE_MAX = {"TEU": 55, "TFEU": 358, "Charter": 54, "ECHR": 59}
# PROPOSED, NOT LIVE: the article's own subject, one word, for the articles a first-year EU law course cites.
# It loosens the signed-off rule "a blank tab is better than a wrong one", so it stays off (_HEADINGS empty) until
# Matej gives his named yes; then set _HEADINGS = _HEADINGS_PROPOSED. His own index would still win.
_HEADINGS_PROPOSED = {("TEU", n): w for n, w in {
    "2": "Values", "3": "Objectives", "4": "Cooperation", "5": "Conferral", "6": "Rights", "7": "Sanctions",
    "13": "Institutions", "14": "Parliament", "16": "Council", "17": "Commission", "19": "Court", "48": "Revision",
    "49": "Accession", "50": "Withdrawal"}.items()}
_HEADINGS_PROPOSED.update({("TFEU", n): w for n, w in {
    "2": "Competences", "3": "Exclusive", "4": "Shared", "6": "Supporting", "18": "Nationality", "20": "Citizenship",
    "21": "Residence", "26": "Market", "28": "Customs", "30": "Duties", "34": "Imports", "35": "Exports",
    "36": "Derogations", "45": "Workers", "49": "Establishment", "56": "Services", "57": "Services", "63": "Capital",
    "101": "Cartels", "102": "Dominance", "107": "Aid", "110": "Taxation", "114": "Harmonisation",
    "157": "Pay", "258": "Infringement", "259": "Infringement", "260": "Penalties", "263": "Annulment",
    "265": "Inaction", "267": "Reference", "268": "Damages", "277": "Illegality", "288": "Instruments",
    "340": "Liability"}.items()})
_HEADINGS_PROPOSED.update({("Charter", n): w for n, w in {"47": "Remedy", "51": "Scope", "52": "Limits", "53": "Level"}.items()})
_HEADINGS: dict = {}
_WEEK_TITLE_TABS = False

_ACRONYMS = {"EU", "EC", "EEC", "TFEU", "TEU", "CJEU", "ECJ", "ECHR", "ECTHR", "IRAC", "WG", "BW", "DCFR", "AG", "ECR",
             "UK", "US", "NL", "CFI", "GC", "QMV", "EP", "ECB", "II", "III", "IV", "MEQR", "MEQRS"}


def _deshout(text: str) -> str:
    """'LECTURE 3A: FREE MOVEMENT OF GOODS' -> 'Lecture 3A: free movement of goods'. Only an all-caps line is
    touched; acronyms and anything with a digit keep their capitals."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4 or sum(ch.isupper() for ch in letters) < 0.8 * len(letters):
        return text
    out, first = [], True
    for tok in re.split(r"(\W+)", text):
        if not tok or not re.search(r"[A-Za-z]", tok):
            out.append(tok); continue
        if tok.upper() in _ACRONYMS or re.search(r"\d", tok):
            out.append(tok)
        else:
            out.append(tok[:1].upper() + tok[1:].lower() if first else tok.lower())
        first = False
    return "".join(out)


_WG = re.compile(r"(?i)\b(?:wg|working\s+group)\b|\bmodel\s+answer|^\s*(?:q\s*\d+|question\s+\d+|answers?)\b")
# An answer to a set question that nobody labelled: its scaffolding ("IRAC structure", "Preliminary question",
# "Advice to ...", "Quick reference card") or a problem's parties as a heading ("Next Gen Pharmacy v German
# Association of Pharmacists") where no case of that name is in the case index.
# 'Facts', 'Question', 'Answer' count only as the whole heading (or before a colon / dash): 'Facts and procedure in
# Art 267' and 'Questions of admissibility' are lecture topics.
_ANSWER_HEAD = re.compile(r"(?i)^\s*(?:irac\b|preliminary\s+question\b(?!s).*\?\s*$|advice\s+to\b|problem\s+question|"
                          r"(?:the\s+)?facts(?:\s+of\s+the\s+(?:problem|question|scenario))?\s*(?:[:—–-]|$)|"
                          r"quick\s+reference(?:\s+card)?\b|(?:question|answer)\s*(?:[:—–-]|$)|conclusion\s+for\s+the\s+client)")
# A party that only a real case has: an EU institution or a Member State ('Commission v Germany'). A problem
# question's parties are invented ('Next Gen Pharmacy v German Association of Pharmacists').
_REAL_PARTY = re.compile(r"(?i)^(?:european\s+)?(?:commission|council|parliament|central\s+bank|ecb|court\s+of\s+auditors|"
                         r"austria|belgium|bulgaria|croatia|cyprus|czech\s+republic|czechia|denmark|estonia|finland|france|"
                         r"germany|greece|hellenic\s+republic|hungary|ireland|italy|latvia|lithuania|luxembourg|malta|"
                         r"netherlands|the\s+netherlands|poland|portugal|romania|slovakia|slovenia|spain|sweden|united\s+kingdom|uk)\b")


def _is_wg(text) -> bool:
    """A working-group answer (a WG note, or a 'WG 2 answers', 'Q1', 'Answer' heading): kept out of the pack's
    outline and rule box, which are for the doctrine, not for answers to set questions."""
    return bool(_WG.search(text or ""))


def _tidy_title(title: str) -> str:
    """'WEEK 2 EU LAW COMPLETE LECTURE NOTES' -> 'EU law' (and then _title looks further); 'Week 1 — X' -> 'X'."""
    t = re.sub(r"(?i)^\s*(?:week|wk)\s*0?\d+\b\s*[—–:\-]?\s*", "", title or "")
    t = re.sub(r"(?i)\b(?:complete|full|final)?\s*lecture\s+notes\b|\bcomplete\s+notes\b", "", t)
    t = _deshout(re.sub(r"\s{2,}", " ", t).strip(" —–:-·"))
    t = re.sub(r"(?i)^lecture\s+notes\s*[:—–-]\s*", "", t)
    return t[:1].upper() + t[1:]


def _source(note_title: str, week, title: str) -> str:
    """The note a case came from, as the From column prints it. A title that says nothing once 'Week N' and
    'complete lecture notes' are gone ('WEEK 2 EU LAW COMPLETE LECTURE NOTES') is named by the week's own title,
    so the page does not carry two names for one week."""
    if _meaningful(_tidy_title(note_title)): return _deshout(note_title)
    return f"Week {week} lecture notes — {title}" if title and not title.startswith("Week ") else _deshout(note_title)


def _meaningful(text: str) -> bool:
    return any(w.lower() not in _HEAD_STOP and len(w) > 2 for w in re.findall(r"[A-Za-zÀ-ÿ]+", text or ""))


_LECTURE = r"(?i)^\s*lecture\s+\d+[a-z]?\s*[:—–-]\s*"


def _title(notes) -> str:
    """The week's title: the first note title that says something once 'Week N' and 'complete lecture notes' are
    gone, else the first real heading in its notes ('Lecture 3A:' dropped), else the note title as tidied."""
    lecture = _LECTURE
    for n in notes:
        t = _tidy_title(n["title"])
        if _meaningful(t): return t
    for n in notes:
        for h in _H1.findall(n.get("body") or "") + _H2.findall(n.get("body") or ""):
            h = re.sub(lecture, "", _deshout(re.sub(r"^\d+[.)]?\s+", "", h.strip(" #*"))))
            if _meaningful(h) and not _is_answer_heading(h) and _outline_key(h) not in _SECTION_ONLY:
                return h[:1].upper() + h[1:]
    return _tidy_title(notes[0]["title"]) or notes[0]["title"]


# Headings that name a box the pack already prints, or the note's own scaffolding, not a topic.
_SECTION_ONLY = {"in one glance", "case map", "leading cases", "table of cases", "cases", "quick reference card",
                 "quick reference", "contents", "sources", "provenance key", "status"}


def _outline_key(h: str) -> str:
    h = re.sub(r"\s*\([^)]*\)\s*$", "", h)                     # "Scope (Lecture 1 & 2, 31 Aug ...)" is "Scope"
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", h.casefold())).strip()


def _is_answer_heading(h: str, case_keys=frozenset(), section: str = "") -> bool:
    """A heading that belongs to an answer to a set question, labelled or not (see _ANSWER_HEAD). A party-name
    heading counts only when both sides are proper names, no case of that name is in the index, and its
    section cites nothing (a real case written up carries a number, an ECLI or a year)."""
    if _is_wg(h) or _ANSWER_HEAD.match(h): return True
    parties = re.match(r"^([A-ZÀ-Ý].{1,59}?)\s+v\.?\s+([A-ZÀ-Ý].{1,79})$", h.strip())
    if not parties: return False
    if any(_REAL_PARTY.match(p.strip()) for p in parties.groups()): return False      # 'Commission v Germany (beer)'
    if re.search(r"\([a-z][^)]{0,30}\)\s*$", h): return False      # a case's nickname, '(beer)', '(Apple)'

    key = _name_key(h)
    if key in case_keys or any(k and re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", key) for k in case_keys): return False
    return not (_dockets(section) or re.search(r"ECLI:|[\[(](?:1[5-9]|20)\d\d[\])]", section))


def _outline(notes, case_keys=frozenset(), title: str = "") -> list:
    """Section headings, numbering stripped ('1 Treaty Framework' as well as '1. ...'), all-caps calmed, each
    heading once, WG answers (labelled or not) and the pack's own boxes left out, and a heading that only
    repeats the week's title ('Lecture 3A: <title>') dropped."""
    out, seen = [], {_outline_key(re.sub(_LECTURE, "", title))} if title else set()
    for n in notes:
        body = n.get("body") or ""
        heads = list(re.finditer(r"^(#{1,2})\s+(.+)$", body, re.M))
        in_wg = False                      # an H2 under a "# WG 2 answers" H1 is an answer, until the next H1
        for i, m in enumerate(heads):
            if m.group(1) == "#":
                in_wg = _is_wg(m.group(2)); continue
            if in_wg: continue
            section = body[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
            h = _deshout(re.sub(r"^\d+[.)]?\s+", "", m.group(2).strip(" #*")).strip())
            key = _outline_key(h)
            if not key or key in seen or key in _SECTION_ONLY: continue
            if _outline_key(re.sub(_LECTURE, "", h)) in seen: continue
            if _is_answer_heading(h, case_keys, section): continue
            seen.add(key); out.append(h)
    return out[:OUTLINE]


def _passing(name: str, body: str) -> bool:
    """Named exactly once, and not in a table row (a case map that lists it is working it)."""
    rows = "\n".join(l for l in (body or "").splitlines() if l.lstrip().startswith("|"))
    return _mentions(name, body) == 1 and _mentions(name, rows) == 0


def _mentions(name: str, body: str) -> int:
    """How often a week's notes name a case, by its first distinctive word ('Cassis', 'Gend', 'Keck')."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ]+", name) if len(w) > 3 and w.lower() not in _CASE_FILLER]
    word = words[0] if words else name        # "Keck" in "Keck and Mithouard": notes shorten to the first word
    return len(re.findall(r"(?i)(?<![A-Za-zÀ-ÿ])" + re.escape(word) + r"(?![A-Za-zÀ-ÿ])", body or ""))


# Doctrines and principles a note may italicise like a case. Exact names only: a real case dropped is worse than
# a doctrine row surviving.
_DOCTRINES = {"direct effect", "indirect effect", "vertical direct effect", "horizontal direct effect", "incidental direct effect",
              "supremacy", "primacy", "state liability", "proportionality", "subsidiarity", "conferral", "sincere cooperation",
              "loyal cooperation", "mandatory requirements", "mutual recognition", "rule of reason", "consistent interpretation",
              "effet utile", "effectiveness", "equivalence", "legal certainty", "legitimate expectations", "non-discrimination",
              "market access", "selling arrangements", "certain selling arrangements", "irac", "acte clair", "acte éclairé",
              "numerus clausus", "nemo dat", "nemo plus", "good faith", "res judicata", "ratio decidendi", "obiter dicta",
              "obiter dictum", "ultra vires", "pre-emption", "general principles", "fundamental rights", "internal market"}
_CASE_FILLER = {"case", "cases", "and", "the", "van", "von", "der", "den", "des", "del", "nv", "bv", "sa", "spa", "gmbh", "ltd", "plc"}
_DOCKET = re.compile(r"(?<![\w/])(?:(?:Case|Joined\s+Cases)\s+)?([CTF])?[-‑]?(\d{1,4})/(\d{2})(?![\d/])(\s+P\b)?")
_YEAR_ONLY = re.compile(r"^\s*[\[(]?(1[5-9]\d\d|20\d\d)[\])]?\s*$")
_YEAR_TAIL = re.compile(r"\s*[\[(](1[5-9]\d\d|20\d\d)[\])]\s*$")
_FOUR = re.compile(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)")
_BRACKET_YEAR = re.compile(r"[\[(](1[5-9]\d\d|20\d\d)[\])]")
_NUMBER = re.compile(r"(?<![\w/])\d{1,5}/(\d{2})(?![\d/])")
# THE ONE RULE (wave-4): a number is not a CJEU docket when anything marks it as another court's. A cite that
# carries such a mark is printed exactly as the notes write it: not restyled, not reordered, and given no year
# read off its number. Only a year the notes write for it prints. What marks a number as another court's:
#  - a register mark right before it, in any text: the German Federal Constitutional Court's '2 BvR 197/83' /
#    '2 BvE 2/08' and the Federal Court of Justice's 'IX ZR 123/04' (capital, small letter, capitals), a dotted
#    abbreviation ('Corte cost. sent. 170/84', 'Pl. ÚS 5/12', 'no. 5856/72'), an application or register number
#    word ('App no', 'Application', 'n.', 'nr'), or a lone capital other than the CJEU's own C / T / F ('K 3/21');
#  - in a citation, any word in front of a bare number that is not the case's own name, 'Case(s)' / 'Joined' /
#    'and', a date, an ECR report or an ECLI: such a word names the court or register the number belongs to;
#  - another court named in the cite, or in the case's name when the cite has no C- / T- / F- docket ('Tyrer v
#    United Kingdom (ECtHR)', 'Granital (Corte costituzionale)', '[1990] 2 AC 85 (HL)');
#  - a number of another shape in the cite: four or more figures with no court letter ('5856/72'), or a full year
#    after the slash ('170/1984', '15/2014').
# An all-capitals word that is the case's own name stays the CJEU's: 'ERT 260/89' is the CJEU's ERT. A General
# Court 'T-' or a 'C-' the notes wrote is printed as written and never removed.
_MARK_WORD = (r"(?:[A-Z][a-z][A-Z]{1,2}|[IVX]{1,5}\s+Z[A-Z]{1,2}|[^\W\d_]{1,8}\.|no|nos|nr|n|App|Appl|Application|"
              r"[ABDEGHJ-SUWYZ]|ÚS|STC|ATC|TK|SK|Kp|Ts|BVerfGE?|BGH|BGHZ|VfGH|OGH)")
# not a court's mark: a company form or a citing word ('United Brands Co. 27/76', 'cf. 26/62'), or 'Marshall I'
_NOT_MARK = r"(?!(?i:cf|see|eg|ie|ibid|op|v|vs|paras?|pp?|ed|eds|ch|art|arts|co|corp|inc|ltd|bros|cie|st|mr|mrs|dr)\.)"
_OTHER_COURT = re.compile(r"(?:(?<![\w.])" + _NOT_MARK + _MARK_WORD + r"\s*|(?<![\w-])[ABDEGHJ-SUWYZ][-‑])$")
_OTHER_NUMBER = re.compile(r"(?:\b\d\s+)?(?<![\w.])(?:[A-Z][a-z][A-Z]{1,2}|[IVX]{1,5}\s+Z[A-Z]{1,2})\s+\d{1,5}/\d{2}(?![\d/])")
_COURT_NAME = re.compile(
    r"(?i)(?:\bECtHR\b|\bE\.?\s?Ct\.?\s?H\.?\s?R\b|\bEComHR\b|Court\s+of\s+Human\s+Rights|Commission\s+of\s+Human\s+Rights|"
    r"\(ECHR\)|,\s*ECHR\s*$|\bBVerfG\w*|\bBGHZ?\b|\bBVerwG\b|\bBFH\b|\bVfGH\b|\bVwGH\b|\bOGH\b|Bundesverfassungsgericht|"
    r"Bundesgerichtshof|Verfassungsgerichtshof|\bCorte\s+cost\w*|Corte\s+(?:suprema|di\s+cassazione)|Consiglio\s+di\s+Stato|"
    r"Cour\s+de\s+cassation|\bCass\.|Conseil\s+(?:d['’]\s?[ÉE]tat|constitutionnel)|Hoge\s+Raad|Raad\s+van\s+State|\bABRvS\b|"
    r"Supreme\s+Court|Constitutional\s+(?:Court|Tribunal|Council)|\bConst\.?\s+(?:Ct|Court)\b|"
    r"\b(?:Federal|Italian|German|French|Dutch|Polish|Czech|Spanish|Danish|Belgian|Austrian|Hungarian|Irish|national)\s+"
    r"(?:constitutional\s+|supreme\s+|administrative\s+)?(?:Court|Ct|Tribunal)\b|High\s+Court|Court\s+of\s+Appeal|House\s+of\s+Lords|"
    r"Privy\s+Council|\bUKSC\b|\bUKHL\b|\bUKPC\b|\bEWCA\b|\bEWHC\b|\(HL\)|\(CA\)|Tribunal\s+(?:Constitucional|Supremo)|"
    r"Trybuna\w*|Ústavn\w+\s+s[úo]d|Højesteret|Högsta\s+domstolen|Korkein|Alkotmánybíróság|Areios\s+Pagos|Curtea\s+Constitu\w+)")
_FOREIGN_SHAPE = re.compile(r"(?<![\w/])\d{1,5}/(?:1[89]|20)\d\d(?![\d/])|(?<![\w/])\d{4,6}/\d{2}(?![\d/])")
_CJEU_WORDS = {"case", "cases", "joined", "and", "en", "et", "judgment", "judgement", "of", "on", "in", "ecr",
               "i", "ii", "p", "cjeu", "ecj", "court", "justice", "decided", "delivered", "ruling", "the",
               "co", "corp", "inc", "ltd", "sa", "nv", "bv", "ag", "gmbh", "spa", "plc", "cie", "kg", "srl", "sarl"}


_NAME_EXTRA = {"case", "cases", "i", "ii", "iii", "co", "corp", "inc", "ltd", "sa", "nv", "bv", "ag", "gmbh", "spa", "plc"}


def _words(text: str) -> set:
    t = unicodedata.normalize("NFKD", (text or "").casefold())
    return set(re.findall(r"[^\W\d_]+", "".join(ch for ch in t if not unicodedata.combining(ch))))


def _another_court(cite: str, name: str = "") -> bool:
    """True when anything marks the row's numbers as another court's (THE ONE RULE above). Such a cite prints
    verbatim and undated unless the notes write its year."""
    cite, name = cite or "", name or ""
    lettered = any(m.group(1) for m in _DOCKET.finditer(cite))
    if _COURT_NAME.search(cite) or (_COURT_NAME.search(name) and not lettered): return True
    if _FOREIGN_SHAPE.search(re.sub(r"ECLI:\S+", "", cite)): return True
    allowed = _CJEU_WORDS | _words(name) | {m.lower() for m in re.findall(_MONTHS, cite, re.I)}
    last = 0
    for m in _DOCKET.finditer(cite):
        before = cite[:m.start()]
        if re.search(r"(?i)\bopinions?\s*$", before): return True        # an Opinion's number: printed as written
        if not m.group(1) and not re.match(r"(?i)(?:joined\s+)?cases?\b", m.group(0)):
            raw_gap = re.sub(r"ECLI:\S+|\bEU:C:\S+|[\[(]\d{4}[\])]", " ", cite[last:m.start()])
            gap = {w for w in _words(raw_gap) if not re.fullmatch(_MONTHS, w, re.I)}
            if re.search(r"[-‑]\s*$", before) and _OTHER_COURT.search(before): return True   # EFTA 'E-9/97'
            if not gap - allowed: pass                                      # its own name, 'Case', a date, a report
            elif re.search(r"\s(?:v|vs)\.?\s", " " + raw_gap + " "): pass   # the parties: 'Procureur du Roi v Dassonville, 8/74'
            else: return True                                               # 'Corte cost. sent.', 'Pl. ÚS', 'K', 'Rewe'
            if _OTHER_COURT.search(before) and not (_words(before[-12:]) & _words(name)): return True
        last = m.end()
    return False


# A year the notes write as a year without brackets: in a date ('19 November 1991'), after 'judgment' / 'decided' /
# 'delivered' ('judgment of 1963'), or standing alone at the end of a cite ('106/77, 1978'). A loose four-figure
# number anywhere else is not one: in 'ECR 1585' it is a page.
_MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WRITTEN_YEAR = re.compile(r"(?i)(?:\b(?:\d{1,2}(?:st|nd|rd|th)?\s+)?" + _MONTHS + r"\.?,?\s+"
                           r"|\b(?:judg(?:e)?ment|decided|delivered|ruling|ruled)\s+(?:of\s+|on\s+|in\s+)?(?:\d{1,2}\s+" + _MONTHS + r"\.?\s+)?"
                           r"|(?:^|,\s*))(1[5-9]\d\d|20\d\d)(?![\d/])(?=\s*(?:[,;)\]]|$|ECR\b))")


def _dockets(text: str):
    """The CJEU / General Court case numbers in a text, as match objects. Not one: an Opinion's number
    ('Opinion 2/13' is an Opinion, never 'Case C-2/13'), an ECtHR application number (four or more figures with
    no court letter: 'Tyrer v UK, 5856/72'), anything after 'no.' / 'Application', or a number right after another
    court's register mark ('2 BvR 197/83', 'Pl. ÚS 5/12', 'K 3/21'; see THE ONE RULE above). A whole citation is
    judged by _another_court, which also reads the words further in front and the courts named."""
    out = []
    for m in _DOCKET.finditer(text or ""):
        before = (text or "")[:m.start()]
        if re.search(r"(?i)\bopinions?\s*$|\b(?:no\.?|nos\.?|application|appl?\.)\s*$", before): continue
        if not m.group(1) and not re.match(r"(?i)(?:joined\s+)?cases?\b", m.group(0)) and _OTHER_COURT.search(before): continue
        if not m.group(1) and len(m.group(2)) >= 4: continue
        out.append(m)
    return out


def _docket(m) -> str:
    """One style for a case number: 'Case 26/62', 'Case C-6/90', 'Case T-47/03', the appeal suffix ' P' kept. The
    court letter is printed exactly as the notes write it: none is added (a bare '6/90' stays 'Case 6/90') and none
    is removed (cases still pending when the General Court opened in 1989 carry 'C-' officially, e.g. Barber
    C-262/88, so a 'C-' on an older number is not an error the pack may correct)."""
    court, num, yy, suffix = m.group(1), int(m.group(2)), m.group(3), " P" if m.group(4) else ""
    return f"Case {court + '-' if court else ''}{num}/{yy}{suffix}"


def _docket_key(d: str) -> str:
    """'Case C-6/90', 'Case 6/90' and 'Case C-6/90 P' compare equal when merging rows (one docket, three spellings)."""
    m = re.search(r"([CTF]-)?(\d+)/(\d{2})", d)
    return f"{'T' if m.group(1) == 'T-' else 'F' if m.group(1) == 'F-' else ''}{int(m.group(2))}/{m.group(3)}"


def _fuller(a: str, b: str) -> str:
    """Of two spellings of one docket, the one that carries more of what the notes wrote ('C-', ' P')."""
    score = lambda d: ("C-" in d) + d.endswith(" P")
    return b if score(b) > score(a) else a


def _trim(text: str) -> str:
    """Strip separators off the ends of what is left of a cite, but never half of a bracket pair: '(1986)' stays."""
    t = text or ""
    while True:
        s = re.sub(r"^[\s,;&+]+|[\s,;&+]+$", "", t)
        if s.startswith("(") and s.count("(") > s.count(")"): s = s[1:]
        if s.endswith(")") and s.count(")") > s.count("("): s = s[:-1]
        if s.startswith("[") and s.count("[") > s.count("]"): s = s[1:]
        if s.endswith("]") and s.count("]") > s.count("["): s = s[:-1]
        if s == t: return s
        t = s


def _cite_parts(cite: str, name: str = ""):
    """(dockets, rest): every case number in a CJEU citation in house style, and what is left (an ECLI, a report),
    verbatim. The case's own name written in front of its number ('ERT 260/89') is already in the name column."""
    ms = _dockets(cite)
    dockets = [_docket(m) for m in ms]
    rest, last = "", 0
    for m in ms:
        rest += (cite or "")[last:m.start()]; last = m.end()
    rest += (cite or "")[last:]
    rest = _trim(re.sub(r"\s*(?:&|\band\b|\+)\s*(?=$|[,;])", "", rest))
    if re.fullmatch(r"(?i)(?:joined\s+)?cases?|", rest.strip()): rest = ""
    if dockets and rest and not re.search(r"\d", rest) and _words(rest) <= _words(name) | _NAME_EXTRA: rest = ""
    return dockets, rest


def _name_key(name: str) -> str:
    """'Van Gend & Loos' and 'Van Gend en Loos', 'Costa v ENEL' and 'Costa/ENEL': one key."""
    t = unicodedata.normalize("NFKD", name.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[/&,.'’()\[\]-]", " ", t)
    return " ".join(w for w in t.split() if w not in {"v", "vs", "en", "and", "et", "und", "the", "case", "cases"})


def _explicit_year(*texts):
    """A year the notes write as a year: the year field of an ECLI, a bracketed [1963] / (1979), or an unbracketed
    year in a date or after 'judgment' / 'decided' (see _WRITTEN_YEAR). A loose four-figure number is not one:
    in 'ECR 1585' it is a page."""
    for t in texts:
        bare = re.sub(r"ECLI:\S+", "", t or "")
        m = (re.search(r"ECLI:[A-Z]{2}:[A-Z]+:(\d{4}):", t or "") or _BRACKET_YEAR.search(bare)
             or _WRITTEN_YEAR.search(bare))
        if m: return int(m.group(1))
    return None


def _yy_years(*texts) -> set:
    """Every year a 'N/YY' number in the texts could stand for (26/62 -> 1962, 2/13 -> 2013)."""
    return {(1900 if int(m.group(1)) >= 50 else 2000) + int(m.group(1)) for t in texts for m in _NUMBER.finditer(t or "")}


def _court_seg(before: str, number: str) -> str:
    """In running text ('*Landtová* Pl. ÚS 5/12 found...'), the court's own mark and the number, verbatim, when
    the words right before the number are another court's mark or name; '' when they are not."""
    piece = re.split(r"[,:;(]", before)[-1]
    start = None
    cm = None
    for cm in _COURT_NAME.finditer(piece): pass
    if cm: start = cm.start()
    elif _OTHER_COURT.search(piece):
        start = _OTHER_COURT.search(piece).start()
    if start is None: return ""
    toks = list(re.finditer(r"\S+", piece[:start]))
    while toks and re.fullmatch(r"[^\W\d_]{1,8}\.|[A-ZÚ][\w]{0,3}|\d", toks[-1].group(0)):
        start = toks.pop().start()
    return (piece[start:].strip() + (" " if not piece.endswith("-") else "") + number).replace("- ", "-").strip()


def _from_notes(cases: list, bodies: dict) -> list:
    """What the case index lost on the way from the note, read back from the note itself. run.py's prose reader
    keeps only the bare number after an *italic* name: '2/08' out of '*Lisbon* (2 BvE 2/08)', 'C-402/05' out of
    '(C-402/05 P)', and 'C-6/90' with the number's year out of '(C-6/90, judgment of 19 November 1991)'. Where the
    note writes the name with that number right after it, the court's own number, the ' P' and the written year are
    taken from the note. Nothing the note does not say is added. Pure; the input is not changed."""
    out = []
    for c in cases or []:
        cite, name = str(c.get("cite") or "").strip(), str(c.get("name") or "").strip()
        c = dict(c)
        if cite and name and len(cite) <= 16:
            hit = None                         # the first mention whose own tail carries the number
            for note in c.get("notes") or []:
                for m in re.finditer(r"(?i)(?<![\w])\*?" + re.escape(name) + r"\*?", bodies.get(note.get("id")) or ""):
                    tail = m.string[m.end():m.end() + 90].split("\n", 1)[0]
                    tail = re.split(r"[*;]", tail, maxsplit=1)[0]                # up to the next case named
                    tail = tail[:tail.find(")") + 1] if ")" in tail else tail      # this case's bracket, not the next one's
                    at = re.search(r"(?<![\w/-])([A-Z][-‑])?" + re.escape(cite) + r"(?![\d/])", tail)
                    if at: hit = (tail, at); break
                if hit: break
            if hit:
                tail, at = hit
                if "(" in tail[:at.start()]:          # in the bracket after the name: read the bracket up to the number
                    seg = _trim(re.sub(r"^\W*?\(", "", tail[:at.end()], count=1))
                    seg = re.sub(r"(?i)^(?:see(?:\s+also)?|cf\.?|e\.g\.,?|also)\s+", "", seg)
                else:                                 # in running text: only a court's own mark right before it
                    seg = _court_seg(tail[:at.start()], at.group(0))
                if at.group(1) and at.group(1)[0] not in "CTF" and not re.match(r"[A-Z]-", cite):
                    seg = seg or at.group(0)          # another court's letter: the EFTA Court's 'E-9/97'
                    if not _another_court(seg, name): seg = at.group(0)
                other = next((o for o in _OTHER_NUMBER.finditer(tail) if o.end() == at.end()), None)
                if not re.match(r"[CTF]-", cite) and (other or (seg and (_another_court(seg, name) or seg == at.group(0) and at.group(1)))):
                    c["cite"], c["year"] = (other.group(0) if other else seg).strip(), None   # another court's, verbatim
                else:
                    if at.group(1) and not re.match(r"[CTF]-", cite):
                        c["cite"] = cite = at.group(0)[0] + "-" + cite.split("-", 1)[-1]   # the 'C-' the note wrote
                    if re.match(r"\s+P\b", tail[at.end():]) and not cite.endswith(" P"):
                        c["cite"] = cite + " P"
                y = _explicit_year(tail[at.end():])
                if y: c["written_year"] = y                                  # a year the note writes for this case stands
        out.append(c)
    return out


def normalise_cases(cases: list) -> list:
    """The case index as the pack prints it: rows naming two cases split only when each name has its own cite,
    a year written into the name moved to the year column, doctrines dropped, CJEU case numbers in one style, and
    the same case under two spellings or two cites merged. Nothing is added: no case number, letter, year or
    citation the notes do not carry. A row's year is the year the notes write (a Year column, [1963] ECR, an
    ECLI), else the year in its case number, flagged 'numbered' because that is when the case reached the Court,
    not when it was decided. Pure; the input is not changed."""
    rows = []
    for c in cases or []:
        raw_name, raw_cite = str(c.get("name") or ""), str(c.get("cite") or "")
        names = [x.strip() for x in raw_name.split(";")]
        cites = [x.strip() for x in raw_cite.split(";")]
        split = len(names) > 1 and len(cites) == len(names) and all(names)
        if not split:                     # one cite for several names: one row, cite and year kept as written
            names, cites = [raw_name.strip()], [raw_cite.strip()]
        for name, cite in zip(names, cites):
            name = re.sub(r"\*|,\s*(?:CJEU|ECJ|ECtHR)$|,?\s*at\s*\[?paras?\b.*$", "", name).strip(" ,")
            year_in_name = None
            m = _YEAR_TAIL.search(name)
            if m: year_in_name, name = int(m.group(1)), name[:m.start()].strip(" ,")
            foreign = _another_court(cite, raw_name) or _COURT_NAME.search(raw_name) and not cite
            dk = [] if foreign else _dockets(name)              # "Walrave 36/74" written into the name
            if dk and dk[-1].end() == len(name.rstrip()):
                cite = cite or dk[-1].group(0); name = name[:dk[-1].start()].strip(" ,(")
            if not name or name.casefold().strip(" .") in _DOCTRINES: continue
            if foreign:                          # THE ONE RULE: another court's cite, exactly as the notes write it
                dockets, rest = [], re.sub(r"\s+", " ", cite).strip()
            else:
                dockets, rest = _cite_parts(cite, name)
            if _YEAR_ONLY.match(rest or ""): year_in_name, rest = year_in_name or int(_FOUR.search(rest).group(1)), ""
            written = _explicit_year(rest, cite) or year_in_name or (c.get("written_year") if not split else None)
            given = c.get("year") if not split else None
            # The index's year may itself be read off a number (run.py's fallback): 2013 from "Opinion 2/13",
            # 1972 from "5856/72". Only a year that no number in the row explains counts as written.
            bare = {int(y) for y in re.findall(r"(?<!\d)\d{4}(?!\d)", _BRACKET_YEAR.sub("", re.sub(r"ECLI:\S+", "", raw_cite)))}
            if not written and given and given not in _yy_years(name, cite, raw_name, raw_cite) and given not in bare:
                written = given                  # ...and a bare figure in the cite ("ECR 1585", "ECR 1337") is a page
            lodged = None
            if dockets:
                yy = int(re.search(r"/(\d{2})", dockets[0]).group(1)); lodged = 1900 + yy if yy >= 50 else 2000 + yy
                if written and written < lodged and not _BRACKET_YEAR.search(raw_cite + raw_name):
                    written = None               # no judgment comes before its case: ', 1629' after 148/78 is a page
            rows.append({"name": name, "dockets": dockets, "rest": rest, "year": written or lodged,
                         "explicit": written is not None, "notes": list(c.get("notes") or [])})
    # merge: same docket, or same name key where the dockets do not disagree
    groups = []
    for r in rows:
        keys = {_docket_key(d) for d in r["dockets"]}
        g = next((g for g in groups if keys & g["keys"]
                  or (_name_key(r["name"]) == _name_key(g["name"]) and not (keys and g["keys"] and keys.isdisjoint(g["keys"])))), None)
        if g is None:
            groups.append({**r, "names": [r["name"]], "dockets": list(r["dockets"]), "keys": set(keys), "notes": list(r["notes"])}); continue
        g["names"].append(r["name"])
        for d in r["dockets"]:
            k = _docket_key(d)
            if k not in g["keys"]: g["dockets"].append(d); g["keys"].add(k)
            else:                           # the fuller spelling of the same docket wins: its 'C-' and its ' P'
                g["dockets"] = [_fuller(x, d) if _docket_key(x) == k else x for x in g["dockets"]]
        g["rest"] = g["rest"] or r["rest"]
        if r["explicit"] and not g["explicit"] or g["year"] is None:
            g["year"], g["explicit"] = r["year"], r["explicit"]
        for note in r["notes"]:
            if all(x["id"] != note["id"] for x in g["notes"]): g["notes"].append(note)
    out = []
    for g in groups:
        name = max(g["names"], key=lambda n: (g["names"].count(n), len(n)))
        cite = " & ".join(g["dockets"]) if g["dockets"] else g["rest"]
        if cite and len(g["dockets"]) > 1: cite = "Joined " + cite.replace(" & Case ", " & ").replace("Case ", "Cases ", 1)
        if g["dockets"] and g["rest"]: cite += ", " + g["rest"]          # the report the notes give stays with it
        out.append({"name": name, "cite": cite, "year": g["year"], "numbered": bool(g["year"]) and not g["explicit"],
                    "notes": g["notes"]})
    return out
