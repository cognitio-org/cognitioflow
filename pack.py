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
    cases = normalise_cases(cases)
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
            "recalled": sorted({c["name"] for c in recalled}, key=str.casefold),
            "method": [label for _, label in essay.LIMBS] if method and len(moves) >= METHOD_HITS else [],
        })
        words[str(week)] = _week_word(title)
    # Each tab's word comes from his own article index where it has the article; otherwise from the title of the
    # week that cites it most and has a word; otherwise none - a blank tab beats a wrong one (signed off). _HEADINGS
    # is empty until Matej says yes to the proposed article subjects (_HEADINGS_PROPOSED).
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
        heading = (index.get(number) or _HEADINGS.get((instrument, number))
                   or next((words[w] for _, w in weekly if words.get(w)), ""))
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


_WG = re.compile(r"(?i)\b(?:wg|working\s+group)\b|\[WG\]|\bmodel\s+answer|^\s*(?:q\s*\d+|question\s+\d+|answers?)\b")
# An answer to a set question that nobody labelled: its scaffolding ("IRAC structure", "Preliminary question",
# "Advice to ...", "Quick reference card") or a problem's parties as a heading ("Next Gen Pharmacy v German
# Association of Pharmacists") where no case of that name is in the case index.
_ANSWER_HEAD = re.compile(r"(?i)^\s*(?:irac\b|preliminary\s+question|advice\s+to\b|(?:the\s+)?facts\b|problem\s+question|"
                          r"quick\s+reference(?:\s+card)?\b|question\b|answer\b|conclusion\s+for\s+the\s+client)")


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


def _is_answer_heading(h: str, case_keys=frozenset()) -> bool:
    """A heading that belongs to an answer to a set question, labelled or not (see _ANSWER_HEAD)."""
    if _is_wg(h) or _ANSWER_HEAD.match(h): return True
    parties = re.match(r"^(.{2,60}?)\s+v\.?\s+(.{2,80})$", h.strip())
    return bool(parties) and _name_key(h) not in case_keys and not any(k and k in _name_key(h) for k in case_keys)


def _wg_section(text: str) -> bool:
    """A section whose provenance tags are all [WG]: the working group's answer, not the doctrine."""
    tags = re.findall(r"\[(LECTURE|WG|SLIDES|READER|SCHUTZE|ADDED)\]", text or "")
    return bool(tags) and all(t == "WG" for t in tags)


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
            if _is_answer_heading(h, case_keys) or _wg_section(m.group(2) + section): continue
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


def _dockets(text: str):
    """The CJEU / General Court case numbers in a text, as match objects. Not one: an Opinion's number
    ('Opinion 2/13' is an Opinion, never 'Case C-2/13'), an ECtHR application number (four or more figures with
    no court letter: 'Tyrer v UK, 5856/72'), or anything after 'no.' / 'Application'."""
    out = []
    for m in _DOCKET.finditer(text or ""):
        before = (text or "")[:m.start()]
        if re.search(r"(?i)\bopinions?\s*$|\b(?:no\.?|nos\.?|application|appl?\.)\s*$", before): continue
        if not m.group(1) and len(m.group(2)) >= 4: continue
        out.append(m)
    return out


def _docket(m) -> str:
    """One style for a case number: 'Case 26/62' (a C- written before the 1989 split dropped, since there was no
    General Court then), 'Case C-6/90', 'Case T-47/03', the appeal suffix ' P' kept. No letter is ever added: a
    bare '6/90' stays 'Case 6/90'."""
    court, num, yy, suffix = m.group(1), int(m.group(2)), m.group(3), " P" if m.group(4) else ""
    if court == "C" and 53 <= int(yy) <= 88: court = None
    return f"Case {court + '-' if court else ''}{num}/{yy}{suffix}"


def _docket_key(d: str) -> str:
    """'Case C-6/90', 'Case 6/90' and 'Case C-6/90 P' compare equal when merging rows (one docket, three spellings)."""
    m = re.search(r"([CTF]-)?(\d+)/(\d{2})", d)
    return f"{'T' if m.group(1) == 'T-' else 'F' if m.group(1) == 'F-' else ''}{int(m.group(2))}/{m.group(3)}"


def _cite_parts(cite: str):
    """(dockets, rest): every case number in a citation in house style, and what is left (an ECLI, a report, an
    ECtHR application number, an Opinion), verbatim."""
    ms = _dockets(cite)
    dockets = [_docket(m) for m in ms]
    rest, last = "", 0
    for m in ms:
        rest += (cite or "")[last:m.start()]; last = m.end()
    rest += (cite or "")[last:]
    rest = re.sub(r"^[\s,;&+()]+|[\s,;&+()]+$", "", re.sub(r"\s*(?:&|\band\b|\+)\s*(?=$|[,;])", "", rest))
    if re.fullmatch(r"(?i)(?:joined\s+)?cases?|", rest.strip()): rest = ""
    return dockets, rest


def _name_key(name: str) -> str:
    """'Van Gend & Loos' and 'Van Gend en Loos', 'Costa v ENEL' and 'Costa/ENEL': one key."""
    t = unicodedata.normalize("NFKD", name.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[/&,.'’()\[\]-]", " ", t)
    return " ".join(w for w in t.split() if w not in {"v", "vs", "en", "and", "et", "und", "the", "case", "cases"})


def _explicit_year(*texts):
    """A year the notes write as a year: the year field of an ECLI, or a bracketed [1963] / (1979). A loose
    four-figure number is not one: in 'ECR 1585' it is a page."""
    for t in texts:
        m = re.search(r"ECLI:[A-Z]{2}:[A-Z]+:(\d{4}):", t or "") or _BRACKET_YEAR.search(re.sub(r"ECLI:\S+", "", t or ""))
        if m: return int(m.group(1))
    return None


def _yy_years(*texts) -> set:
    """Every year a 'N/YY' number in the texts could stand for (26/62 -> 1962, 2/13 -> 2013)."""
    return {(1900 if int(m.group(1)) >= 50 else 2000) + int(m.group(1)) for t in texts for m in _NUMBER.finditer(t or "")}


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
            dk = _dockets(name)                                 # "Walrave 36/74" written into the name
            if dk and dk[-1].end() == len(name.rstrip()):
                cite = cite or dk[-1].group(0); name = name[:dk[-1].start()].strip(" ,(")
            if not name or name.casefold().strip(" .") in _DOCTRINES: continue
            dockets, rest = _cite_parts(cite)
            if _YEAR_ONLY.match(rest or ""): year_in_name, rest = year_in_name or int(_FOUR.search(rest).group(1)), ""
            written = _explicit_year(rest, cite) or year_in_name
            given = c.get("year") if not split else None
            # The index's year may itself be read off a number (run.py's fallback): 2013 from "Opinion 2/13",
            # 1972 from "5856/72". Only a year that no number in the row explains counts as written.
            if not written and given and given not in _yy_years(name, cite, raw_name, raw_cite):
                written = given
            lodged = None
            if dockets:
                yy = int(re.search(r"/(\d{2})", dockets[0]).group(1)); lodged = 1900 + yy if yy >= 50 else 2000 + yy
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
            elif d.endswith(" P"):          # the fuller spelling of the same docket wins: keep its suffix
                g["dockets"] = [d if _docket_key(x) == k else x for x in g["dockets"]]
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
