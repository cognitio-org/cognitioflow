"""The printed pack (Phase 18d): what a course's notes already say, laid out for paper. Pure, no database, no model.

Decided with Matej (Phase 18 brief, decision 7, signed off 2026-09-30): the pack is for revising at home and never
goes into the exam. A page per syllabus week - the rule (the note's opening box), the outline, the leading cases
in the order they were decided with the note each came from, and the exam method's steps where the week's notes
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
        ids = {n["id"] for n in notes}
        body = "\n\n".join(n.get("body") or "" for n in notes)
        title = _title(notes) if notes else f"Week {week}"
        rule = next((r for r in (_rule(n.get("body")) for n in notes if not _is_wg(n.get("title"))) if r), "")
        outline = _outline(notes)
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
                       "note": _deshout(next(x["title"] for x in c["notes"] if x["id"] in ids))} for c in own[:CASES]],
            "more_cases": max(0, len(own) - CASES),
            "recalled": sorted({c["name"] for c in recalled}, key=str.casefold),
            "method": [label for _, label in essay.LIMBS] if method and len(moves) >= METHOD_HITS else [],
        })
        words[str(week)] = _week_word(title) or next((w for w in map(_week_word, outline) if w), "")
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
# or named an article that does not exist. Everything below only reformats what the notes say: no case, year or
# citation is added that the notes do not carry.

_ARTICLE_MAX = {"TEU": 55, "TFEU": 358, "Charter": 54, "ECHR": 59}
# The article's own subject, one word, for the articles a first-year EU law course cites. His own index wins.
_HEADINGS = {("TEU", n): w for n, w in {
    "2": "Values", "3": "Objectives", "4": "Cooperation", "5": "Conferral", "6": "Rights", "7": "Sanctions",
    "13": "Institutions", "14": "Parliament", "16": "Council", "17": "Commission", "19": "Court", "48": "Revision",
    "49": "Accession", "50": "Withdrawal"}.items()}
_HEADINGS.update({("TFEU", n): w for n, w in {
    "2": "Competences", "3": "Exclusive", "4": "Shared", "6": "Supporting", "18": "Nationality", "20": "Citizenship",
    "21": "Residence", "26": "Market", "28": "Customs", "30": "Duties", "34": "Imports", "35": "Exports",
    "36": "Derogations", "45": "Workers", "49": "Establishment", "56": "Services", "57": "Services", "63": "Capital",
    "101": "Cartels", "102": "Dominance", "107": "State-aid", "110": "Taxation", "114": "Harmonisation",
    "157": "Equal-pay", "258": "Infringement", "259": "Infringement", "260": "Penalties", "263": "Annulment",
    "265": "Inaction", "267": "Reference", "268": "Damages", "277": "Illegality", "288": "Instruments",
    "340": "Liability"}.items()})
_HEADINGS.update({("Charter", n): w for n, w in {"47": "Remedy", "51": "Scope", "52": "Limits", "53": "Level"}.items()})

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


_WG = re.compile(r"(?i)\b(?:wg|working\s+group|tutorial)\b|\bmodel\s+answer|^\s*(?:q\s*\d+|question\s+\d+|answers?)\b")


def _is_wg(text) -> bool:
    """A working-group answer (a WG note, or a 'WG 2 answers', 'Q1', 'Answer' heading): kept out of the pack's
    outline and rule box, which are for the doctrine, not for answers to set questions."""
    return bool(_WG.search(text or ""))


def _tidy_title(title: str) -> str:
    """'WEEK 2 EU LAW COMPLETE LECTURE NOTES' -> 'EU law' (and then _title looks further); 'Week 1 — X' -> 'X'."""
    t = re.sub(r"(?i)^\s*(?:week|wk)\s*0?\d+\b\s*[—–:\-]?\s*", "", title or "")
    t = re.sub(r"(?i)\b(?:complete|full|final)?\s*lecture\s+notes\b|\bcomplete\s+notes\b", "", t)
    return _deshout(re.sub(r"\s{2,}", " ", t).strip(" —–:-·"))


def _meaningful(text: str) -> bool:
    return any(w.lower() not in _HEAD_STOP and len(w) > 2 for w in re.findall(r"[A-Za-zÀ-ÿ]+", text or ""))


def _title(notes) -> str:
    """The week's title: the first note title that says something once 'Week N' and 'complete lecture notes' are
    gone, else the first real heading in its notes ('Lecture 3A:' dropped), else the note title as tidied."""
    lecture = r"(?i)^\s*lecture\s+\d+[a-z]?\s*[:—–-]\s*"
    for n in notes:
        if _is_wg(n.get("title")): continue
        t = _tidy_title(n["title"])
        if _meaningful(t): return t
    for n in notes:
        if _is_wg(n.get("title")): continue
        for h in _H1.findall(n.get("body") or "") + _H2.findall(n.get("body") or ""):
            h = re.sub(lecture, "", _deshout(re.sub(r"^\d+[.)]?\s+", "", h.strip(" #*"))))
            if _meaningful(h) and not _is_wg(h) and _outline_key(h) not in _SECTION_ONLY:
                return h[:1].upper() + h[1:]
    return _tidy_title(notes[0]["title"]) or notes[0]["title"]


# Headings that name a box the pack already prints, or the note's own scaffolding, not a topic.
_SECTION_ONLY = {"in one glance", "case map", "leading cases", "table of cases", "cases", "quick reference card",
                 "quick reference", "contents", "sources", "provenance key", "status"}


def _outline_key(h: str) -> str:
    h = re.sub(r"\s*\([^)]*\)\s*$", "", h)                     # "Scope (Lecture 1 & 2, 31 Aug ...)" is "Scope"
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", h.casefold())).strip()


def _outline(notes) -> list:
    """Section headings, numbering stripped ('1 Treaty Framework' as well as '1. ...'), all-caps calmed, each
    heading once, WG answers and the pack's own boxes left out."""
    out, seen = [], set()
    for n in notes:
        if _is_wg(n.get("title")): continue
        for h in _H2.findall(n.get("body") or ""):
            h = _deshout(re.sub(r"^\d+[.)]?\s+", "", h.strip(" #*")).strip())
            key = _outline_key(h)
            if not key or key in seen or key in _SECTION_ONLY or _is_wg(h): continue
            seen.add(key); out.append(h)
    return out[:OUTLINE]


def _passing(name: str, body: str) -> bool:
    """Named exactly once, and not in a table row (a case map that lists it is working it)."""
    rows = "\n".join(l for l in (body or "").splitlines() if l.lstrip().startswith("|"))
    return _mentions(name, body) == 1 and _mentions(name, rows) == 0


def _mentions(name: str, body: str) -> int:
    """How often a week's notes name a case, by its most distinctive word ('Cassis', 'Gend', 'Costa')."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ]+", name) if len(w) > 3 and w.lower() not in _CASE_FILLER]
    word = max(words, key=len) if words else name
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
_DOCKET = re.compile(r"(?<![\w/])(?:(?:Case|Joined\s+Cases)\s+)?([CTF])?[-‑]?(\d{1,4})/(\d{2})(?!\d)")
_YEAR_ONLY = re.compile(r"^\s*[\[(]?(1[5-9]\d\d|20\d\d)[\])]?\s*$")
_YEAR_TAIL = re.compile(r"\s*[\[(](1[5-9]\d\d|20\d\d)[\])]\s*$")
_FOUR = re.compile(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)")


def _docket(court, num, yy) -> str:
    """One style for case numbers: 'Case 26/62' before the 1989 split, 'Case C-6/90' after, 'Case T-…' kept."""
    y = int(yy)
    if court in ("T", "F"):
        return f"Case {court}-{int(num)}/{yy}"
    return f"Case {int(num)}/{yy}" if 53 <= y <= 88 else f"Case C-{int(num)}/{yy}"


def _cite_parts(cite: str):
    """(dockets, rest): every case number in a citation in house style, and what is left (an ECLI, a report)."""
    dockets = [_docket(m.group(1), m.group(2), m.group(3)) for m in _DOCKET.finditer(cite or "")]
    rest = _DOCKET.sub("", cite or "")
    rest = re.sub(r"^[\s,;&+()]+|[\s,;&+()]+$", "", re.sub(r"\s*(?:&|and|\+)\s*(?=$|[,;])", "", rest))
    if re.fullmatch(r"(?i)(?:joined\s+)?cases?|", rest.strip()): rest = ""
    return dockets, rest


def _name_key(name: str) -> str:
    """'Van Gend & Loos' and 'Van Gend en Loos', 'Costa v ENEL' and 'Costa/ENEL': one key."""
    t = unicodedata.normalize("NFKD", name.casefold())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[/&,.'’()\[\]-]", " ", t)
    return " ".join(w for w in t.split() if w not in {"v", "vs", "en", "and", "et", "und", "the", "case", "cases"})


def _explicit_year(*texts):
    """A four-figure year written down ([1963] ECR 1, ECLI:EU:C:1963:1), which beats a docket's lodging year."""
    for t in texts:
        m = re.search(r"ECLI:[A-Z]{2}:[A-Z]+:(\d{4}):", t or "") or _FOUR.search(re.sub(r"ECLI:\S+", "", t or ""))
        if m: return int(m.group(1))
    return None


def normalise_cases(cases: list) -> list:
    """The case index as the pack prints it: rows naming two cases split, a year written into the name dropped,
    doctrines dropped, case numbers in one style, and the same case under two spellings or two cites merged.
    Pure; the input is not changed."""
    rows = []
    for c in cases or []:
        names = [x.strip() for x in str(c.get("name") or "").split(";")]
        cites = [x.strip() for x in str(c.get("cite") or "").split(";")]
        if len(names) > 1 and len(cites) not in (1, len(names)) or not all(names):
            names, cites = [str(c.get("name") or "").strip()], [str(c.get("cite") or "")]
        for i, name in enumerate(names):
            cite = cites[i] if len(cites) == len(names) else (cites[0] if len(names) == 1 else "")
            name = re.sub(r"\*|,\s*(?:CJEU|ECJ|ECtHR)$|,?\s*at\s*\[?paras?\b.*$", "", name).strip(" ,")
            year_in_name = None
            m = _YEAR_TAIL.search(name)
            if m: year_in_name, name = int(m.group(1)), name[:m.start()].strip(" ,")
            dk = _DOCKET.search(name)                          # "Walrave 36/74" written into the name
            if dk and dk.end() == len(name.rstrip()):
                cite = cite or dk.group(0); name = name[:dk.start()].strip(" ,(")
            if not name or name.casefold().strip(" .") in _DOCTRINES: continue
            dockets, rest = _cite_parts(cite)
            if _YEAR_ONLY.match(rest or ""): year_in_name, rest = year_in_name or int(_FOUR.search(rest).group(1)), ""
            explicit = _explicit_year(rest, cite if not dockets else "") or year_in_name
            year = explicit or (c.get("year") if len(names) == 1 else None)
            if year is None and dockets:
                yy = int(dockets[0].rsplit("/", 1)[1]); year = 1900 + yy if yy >= 50 else 2000 + yy
            rows.append({"name": name, "dockets": dockets, "rest": rest, "year": year, "explicit": explicit is not None,
                         "notes": list(c.get("notes") or [])})
    # merge: same docket, or same name key where the dockets do not disagree
    groups = []
    for r in rows:
        g = next((g for g in groups if set(r["dockets"]) & set(g["dockets"])
                  or (_name_key(r["name"]) == _name_key(g["name"]) and not (r["dockets"] and g["dockets"] and set(r["dockets"]).isdisjoint(g["dockets"])))), None)
        if g is None:
            groups.append({**r, "names": [r["name"]], "dockets": list(r["dockets"]), "notes": list(r["notes"])}); continue
        g["names"].append(r["name"])
        g["dockets"] += [d for d in r["dockets"] if d not in g["dockets"]]
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
        out.append({"name": name, "cite": cite, "year": g["year"], "notes": g["notes"]})
    return out
