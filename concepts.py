"""Concepts: the thing a question is about, held once instead of re-derived from raw text each time.

A card written straight from a file is a card about a paragraph. Nothing connects it to the same
doctrine met three weeks earlier, or to the same reasoning in another course, so a deck grows without
ever covering anything. A concept is the unit that persists: a rule, a test and its limbs, a case, an
article, with the traps that catch students and the authority it rests on.

Two rules keep this from becoming a machine for confident invention:

1. **Every concept must quote its source.** The model returns the sentence it read the rule from, and
   `grounded()` checks that sentence actually appears in the passage — a plain string check, not a
   judgement. A concept whose quote is not in the text is dropped, not saved. That is the cheapest
   guard against the failure the legal-AI literature keeps measuring: a statement that is *about* the
   right thing and *supported by* nothing.
2. **It never invents an authority.** A case or article name is carried through only as written.
   Resolving it against the `authorities` table is a separate step with its own evidence.

The model call is the cheap tier, never the strong one, and the parsing below is pure so it can be
tested against a fixture without a network.
"""

import json
import re
import uuid

KINDS = ("rule", "test", "case", "article", "doctrine", "exception")
MAX_CONCEPTS = 18          # one week of one course: more than this and the model is padding
MAX_NAME = 90
MAX_STATEMENT = 700
QUOTE_MIN = 25             # a "quote" shorter than this matches everything and proves nothing

EXTRACT_RULES = """You read one week of a law student's course material and list the concepts it teaches.

A concept is something a question can be asked about: a rule, a test with limbs, a case and what it
decided, an article, a doctrine, or an exception. It is not a topic heading and not a summary.

Return ONLY a JSON object:
{"concepts": [{
  "name": "Dassonville formula",
  "kind": "test",
  "statement": "Any trading rule capable of hindering intra-EU trade, directly or indirectly, actually or potentially, is a measure having equivalent effect.",
  "limbs": ["a trading rule of a Member State", "capable of hindering trade", "directly or indirectly, actually or potentially"],
  "traps": ["treating Cassis as an alternative to Dassonville rather than the step after it"],
  "authority": "C-8/74",
  "method_tag": "free movement",
  "core": true,
  "quote": "the exact sentence from the material that states this, copied character for character",
  "confusable_with": ["Cassis de Dijon", "Keck"]
 }]}

Rules:
- Work only from the material given. If it does not teach a concept, do not list it.
- `quote` must be copied from the material exactly. It is checked. A concept whose quote is not found
  is thrown away, so paraphrasing there costs you the whole entry.
- `authority` only if the material names one: the case the concept comes from (when the material is one judgment,
  that judgment itself, named in its title, never a case it merely cites), as the short name students
  use for it and its number as the material prints it (for example "Van Gend en Loos, Case 26/62";
  "Dassonville, Case 8/74"). Never add a "C-" prefix the material does not print, never a paragraph number,
  and never construct a case number or an article. Name
  an article with its Treaty as the material prints it (Article 30 of the EEC Treaty); never convert old
  numbers to current ones.
- `core` is true only for a rule this judgment is principally cited for in a law course (usually one
  doctrine, two at most), false for a side issue the case happened to raise. Give false for every provision the Court merely applies or dismisses.
- Take only the rule of law this judgment is cited for: what the Court itself decides or states as law.
  Skip the parties' arguments, the facts, the procedure, and every provision the Court merely applies or
  dismisses to decide this one case (a competition, monopoly, establishment or sex-equality provision the
  case happened to raise). If the judgment is cited for one doctrine, list that doctrine's rules, not the
  case's side issues.
- `traps` are mistakes a student actually makes on this concept, from the material's own warnings.
- `method_tag` is the reasoning at work, in two or three words, so the same reasoning can be
  recognised in another course: proportionality, direct effect, remedies, burden of proof, formation,
  transfer of title.
- At most %d concepts, the ones an exam would actually test.
""" % MAX_CONCEPTS


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _words_only(text: str) -> str:
    """Lowercase words separated by single spaces: punctuation, quote marks, dashes and hyphenation are ignored."""
    return " ".join(re.findall(r"[^\W_]+", (text or "").lower()))


def grounded(quote: str, haystack: str) -> bool:
    """Is this quote really in the material? Case, whitespace and punctuation (curly quotes, dashes) are forgiven;
    the words and their order are not."""
    q = _norm(quote)
    if len(q) < QUOTE_MIN:
        return False
    return q in _norm(haystack) or _words_only(quote) in _words_only(haystack)


def clip(text: str, n: int) -> str:
    """text cut to at most n characters at a sentence end, else at a word end with an ellipsis: never mid-word."""
    t = str(text or "").strip()
    if len(t) <= n:
        return t
    cut = t[:n]
    k = max(cut.rfind(". "), cut.rfind("; "), cut.rfind("? "))
    if k >= n * 0.5:
        return cut[:k + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(" ,;:") + "\u2026"


def clean(candidate: dict, material: str) -> dict:
    """One model candidate to a saveable concept, or {} when it fails a rule."""
    if not isinstance(candidate, dict):
        return {}
    name = re.sub(r"\s+", " ", str(candidate.get("name", "") or "")).strip(" .,;:\"'")[:MAX_NAME]
    statement = clip(re.sub(r"\s+", " ", str(candidate.get("statement", "") or "")), MAX_STATEMENT)
    if not name or not statement:
        return {}
    if not grounded(candidate.get("quote", ""), material):
        return {}
    kind = str(candidate.get("kind", "") or "").strip().lower()
    listy = lambda v: [re.sub(r"\s+", " ", str(x)).strip() for x in v if str(x).strip()][:6] if isinstance(v, list) else []
    return {
        "name": name,
        "kind": kind if kind in KINDS else "rule",
        "statement": statement,
        "limbs": listy(candidate.get("limbs")),
        "traps": listy(candidate.get("traps")),
        "authority": str(candidate.get("authority", "") or "").strip()[:80],
        "method_tag": re.sub(r"\s+", " ", str(candidate.get("method_tag", "") or "")).strip().lower()[:40],
        "quote": re.sub(r"\s+", " ", str(candidate.get("quote", ""))).strip()[:400],
        "confusable_with": listy(candidate.get("confusable_with")),
        "core": candidate.get("core", True) is not False and str(candidate.get("core", True)).lower() != "false",
    }


def parse(payload, material: str, max_n: int = MAX_CONCEPTS) -> tuple:
    """(concepts, dropped) from a model reply. Pure: no database, no network."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload[payload.find("{"): payload.rfind("}") + 1])
        except ValueError:
            return [], ["the reply was not JSON"]
    items = (payload or {}).get("concepts") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return [], ["the reply carried no concepts list"]
    kept, dropped, seen = [], [], set()
    for raw in items[:max_n * 2]:
        got = clean(raw, material)
        if not got:
            name = (raw or {}).get("name", "?") if isinstance(raw, dict) else "?"
            dropped.append(f"{name}: its quote is not in the material")
            continue
        if not got.get("core", True):
            dropped.append(f"{got['name']}: a side issue of its source")
            continue
        key = _norm(got["name"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(got)
    return kept[:max_n], dropped


def rows_for_save(concepts, cid: str, week: str, now: float, source_file: str = "", source_note: str = "") -> list:
    """The tuples the courses' concepts table wants, in column order."""
    out = []
    for c in concepts:
        out.append((uuid.uuid4().hex, cid, c["name"], c["kind"], week, c["statement"],
                    json.dumps(c["limbs"]), json.dumps(c["traps"]), c["authority"],
                    source_file, source_note, "", c["method_tag"], now, now))
    return out


def pairs_for_links(concepts, by_name: dict) -> list:
    """(a_id, b_id, relation) for every confusable the model named that already exists as a concept.
    A name the course never taught is not a link — it is a guess, and it is left out."""
    links = []
    for c in concepts:
        a = by_name.get(_norm(c["name"]))
        if not a:
            continue
        for other in c["confusable_with"]:
            b = by_name.get(_norm(other))
            if b and b != a:
                links.append((a, b, "confusable"))
    return links


# ---------------------------------------------------------------- questions, written from the concept

DOCTRINE_NOTES = """EU-law precision (use only where the concept touches it; none of this is a source to cite):
- Direct effect (Van Gend en Loos, Case 26/62) is not direct applicability (Treaty text on regulations, Article 189 of the EEC Treaty).
  Never credit a case with "establishing" direct applicability. Its conditions are a clear and precise, unconditional provision that
  needs no further national or Union measure; "the spirit, the general scheme and the wording" is how the Court read the Treaty, not the conditions.
- Article 12 of the EEC Treaty is a standstill clause: it forbids NEW customs duties and INCREASES after the Treaty entered into
  force (1 January 1958). A duty a State has levied for years at the same rate is not an infringement of Article 12. A problem on it
  must have the State raise a duty, or reclassify a product into a higher one, after that date.
- Primacy is Costa v ENEL (Case 6/64). Simmenthal (Case 106/77) adds that every national court must of its own motion set aside or
  leave unapplied conflicting national law, earlier or later, without waiting for the legislature or a constitutional court. Conflicting
  national law is inapplicable, never "invalid" or "void". Van Gend is not about primacy.
- A rule that applies only to imports, or only to products of other Member States, is directly discriminatory: only the grounds
  listed in Article 36 can justify it, never the mandatory requirements of Cassis de Dijon (Case 120/78), which serve indistinctly applicable rules.
- Protection of industrial and commercial property is a ground in Article 36, not a mandatory requirement. Consumer protection and
  fairness of commercial transactions are mandatory requirements, not Article 36 grounds.
- Keck (Joined Cases C-267/91 and C-268/91) did not overrule Dassonville. It takes certain selling arrangements outside Article 30
  of the EEC Treaty (now Article 34 TFEU) only if they apply to all relevant traders and affect domestic and imported products alike in law and in fact.
- Marshall (Case 152/84): a directive has no horizontal direct effect; it can be relied on against the State in any capacity.
  Van Gend's conditions are about Treaty provisions; never use Van Gend as the authority for whether a directive provision has direct effect.
- Equal treatment of the sexes protects men and women alike. Do not build a problem whose answer turns on the claimant's sex
  unless the rule is stated for that sex; keep facts to what the source decided.
"""

GENERATE_RULES = """You write revision material for a law student, from one concept he has been taught.

You are given the concept as his course stated it: the rule, its limbs, the traps his material warns
about, and the authority it rests on. Write only from that. Do not add a case, an article or a rule
that is not in what you were given — anything you cite is checked against it, and a question citing
something else is thrown away.

Return ONLY JSON:
{"cards": [{"front": "...", "back": "..."}],
 "question": {"question": "...", "steps": ["..."], "model": "..."}}

The cards (two or three):
- One asks the rule and gets the rule back, in his course's own words.
- Where the concept has limbs, one asks for the limbs in order.
- Where the concept has a trap, one is built so that falling for the trap is the wrong answer.
- A card is a question and its answer, never a topic. "Article 34" is not a card.
- Every answer names the case by its short name and number, and the article it rests on, exactly as the
  concept gives them (its name, statement and authority). Never give a paragraph number. Never write the
  answer by repeating the question.
- Plain text only: no markdown, no asterisks, no lists with hyphens inside a card.
- Write an article exactly as the concept does, with its Treaty ("Article 30 of the EEC Treaty"); never
  change its number or its Treaty, and never convert it to the current numbering.
- Doctrine is exact. Direct effect is the Van Gend en Loos idea; "directly applicable" is a different
  Treaty term (regulations). Do not swap them, and do not credit one case with another case's holding.
- In a problem, name hypothetical laws and measures by description ("the Act", "the minister's decree", "a
  national rule"); never invent a case number, a regulation or directive number, an ECLI or a Treaty article.
  Only authority the concept gave you may carry a number.
- Facts must fit the rule's real shape. Give the facts every element the answer needs (a date, who acted, whether a duty
  rose or was merely kept) so the model answer never has to assume one.
- Write emphasis as words, never with asterisks or underscores.

The question is one applied problem, in the shape a two-hour written exam uses:
- Short facts with named parties that force the concept to be used, not recited.
- `steps` is the stappenplan the answer must walk: the checkpoints a marker looks for, in order.
- `model` is the answer written the way a good student would, naming the authority at the right step.
- Where the concept has limbs, at least one limb must be genuinely contestable on your facts. A
  problem whose answer is obvious at every step teaches nothing.
"""

EXTRACT_RULES += "\n" + DOCTRINE_NOTES
GENERATE_RULES += "\n" + DOCTRINE_NOTES

CITE = re.compile(r"(?i)\b(C[-\u2011]\d{1,4}/\d{2,4}|ECLI:[A-Z:0-9.]+|Art(?:icle)?\.?\s*\d+[a-z]?(?:\(\d+\))?|(?:Directive|Regulation|Decision)\s+(?:\((?:EU|EC|EEC)\)\s*)?(?:No\.?\s*)?\d{2,4}/(?:\d{1,4}|XX)(?:/(?:EU|EC|EEC))?)\b")


ART_INSTR = re.compile(r"(?i)\bart(?:icle)?\.?\s*(\d+)[a-z]?(?:\(\d+\))?\s+(?:of\s+the\s+)?(TFEU|EEC|EC|TEC|TEU)\b")


def citations_ok(text: str, concept: dict) -> bool:
    """Every case number and article in generated text must already appear in the concept it came
    from. A model that reaches for another authority is reaching past the material, which is the
    failure this whole layer exists to prevent."""
    known = _norm(" ".join([concept.get("statement", ""), concept.get("authority", ""),
                            " ".join(concept.get("limbs") or []), " ".join(concept.get("traps") or []),
                            concept.get("name", "")]))
    # An article keeps its Treaty: "Article 30 EEC" in the concept may not come back as "Article 30 TFEU" (that
    # number means customs duties in the current Treaty). Same number with another Treaty is a different article.
    have = {(n, i.upper().replace("TEC", "EC")) for n, i in ART_INSTR.findall(known)}
    for n, i in ART_INSTR.findall(_norm(text)):
        i = i.upper().replace("TEC", "EC")
        if (n, i) not in have and any(n == hn and i != hi for hn, hi in have):
            return False
    for found in CITE.findall(text or ""):
        token = _norm(found).replace("article", "art").replace(".", "").replace(" ", "")
        if token not in known.replace("article", "art").replace(".", "").replace(" ", ""):
            return False
    return True


# ---------------------------------------------------------------- clean items (deck Must 10)
_STOP = frozenset("a an the of in on at to for and or is are was were be been by with as that this it its from what which who how why does do did not under any may can must shall if then than when where whether into".split())
_WORD = re.compile(r"[a-z0-9]+")
TEST_TEXT = re.compile(r"(?i)\b(testcase|test case|number\d+|lorem ipsum|placeholder)\b")
_MD_EMPH = re.compile(r"(\*+|__|`+)")   # any asterisk run: **bold**, *italic*, a stray *
DUP_FRONT = 0.9      # [Claude-set] near-duplicate fronts within one week
ECHO_ANSWER = 0.8    # [Claude-set] an answer that only repeats its question


def words(text: str) -> frozenset:
    return frozenset(w for w in _WORD.findall((text or "").lower()) if w not in _STOP)


def jaccard(a, b) -> float:
    a, b = frozenset(a), frozenset(b)
    return len(a & b) / len(a | b) if (a or b) else 1.0


def plain(text: str) -> str:
    """Model text as one plain line: emphasis markers and heading hashes removed, whitespace collapsed."""
    t = re.sub(r"(?i)<\s*br\s*/?\s*>", " ", str(text or ""))
    t = re.sub(r"</?\s*(b|i|em|strong|span)\s*>", "", t, flags=re.I)
    t = re.sub(r"</?\s*(p|ul|ol|li|div|h[1-6])\s*>", " ", t, flags=re.I)
    t = _MD_EMPH.sub("", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", t)
    t = re.sub(r"\bCommission v(?:\.)? (?:the )?Italian Republic\b", "Commission v Italy", t)   # the Court's party name; students say Italy
    return re.sub(r"\s+", " ", t).strip()


def bad_text(text: str) -> str:
    """Why this text is not a clean card or problem, or ''. Raw JSON, code fences and test text fail."""
    t = str(text or "")
    if "```" in t or re.match(r"\s*[\[{]\s*\"", t):
        return "raw markdown or JSON"
    if TEST_TEXT.search(t):
        return "test text"
    return ""


def dup_of(front: str, seen_fronts) -> str:
    """The earlier front this one repeats (exact after normalising, or Jaccard >= DUP_FRONT), or ''."""
    w = words(front)
    for other in seen_fronts:
        if _norm(other) == _norm(front) or (w and jaccard(w, words(other)) >= DUP_FRONT):
            return other
    return ""


def echoes(question: str, answer: str) -> bool:
    return jaccard(words(question), words(answer)) >= ECHO_ANSWER


_NAMES_AUTHORITY = re.compile(r"(?i)\b(art(?:icle)?\.?\s*\d|case\s+c?[-\u2011]?\s*\d|joined cases|c[-\u2011]\d{1,4}/\d{2,4}|ECLI:)")


def pretty_source(name: str) -> str:
    """A file name as a reader would write it: 'commission v italy trailers c 110 05.html' -> 'Commission v Italy trailers, C-110/05'."""
    n = re.sub(r"\.(html?|xhtml|pdf|docx?|txt|md)$", "", str(name or "").strip(), flags=re.I)
    n = re.sub(r"[_]+", " ", n)
    if " " not in n: n = n.replace("-", " ")
    n = re.sub(r"\s+", " ", n).strip(" .")
    if n == n.lower():
        n = " ".join(w if w in ("v", "en", "de", "and", "of", "the", "c") else w.capitalize() for w in n.split())
    n = re.sub(r"(?i)\s+(c)[ -](\d{1,4}) (\d{2})$", lambda m: f", C-{m.group(2)}/{m.group(3)}", n)
    n = re.sub(r"\s+(\d{1,4}) (\d{2})$", lambda m: f", Case {m.group(1)}/{m.group(2)}", n)
    return n[:1].upper() + n[1:] if n else n



def with_authority(answer: str, concept: dict) -> str:
    """An answer that states a rule but names no case or article gets the concept's own authority as its source,
    so every answer says where it comes from. Nothing is added that the concept does not carry."""
    auth = re.sub(r"\s+", " ", str(concept.get("authority") or "")).strip(" .")
    if not auth and concept.get("source_name"):
        auth = "source: " + pretty_source(concept["source_name"])   # no authority named: say which file it came from
    if not auth or _NAMES_AUTHORITY.search(answer or "") or _norm(auth) in _norm(answer):
        return answer
    return f"{answer.rstrip()} ({auth})"


def clean_cards(payload, concept: dict, limit: int = 3) -> tuple:
    """(cards, dropped) — each card a {front, back} that cites nothing the concept did not."""
    items = (payload or {}).get("cards") if isinstance(payload, dict) else None
    kept, dropped = [], []
    for raw in (items or [])[:limit * 2]:
        if not isinstance(raw, dict):
            continue
        why = bad_text(raw.get("front", "")) or bad_text(raw.get("back", ""))
        front, back = plain(raw.get("front", "")), plain(raw.get("back", ""))
        if len(front) < 8 or len(back) < 8:
            dropped.append("a card with no question or no answer")
            continue
        if why:
            dropped.append(f"a card with {why}: {front[:60]}")
            continue
        if echoes(front, back):
            dropped.append(f"a card whose answer only repeats the question: {front[:60]}")
            continue
        if not citations_ok(front + " " + back, concept):
            dropped.append(f"a card citing an authority the concept does not carry: {front[:60]}")
            continue
        other = foreign_case(front + " " + back, concept)
        if other:
            dropped.append(f"a card on a case other than its source ({other}): {front[:60]}")
            continue
        slip = doctrine_slip(front + " " + back)
        if slip:
            dropped.append(f"a card with a doctrine slip ({slip}): {front[:60]}")
            continue
        kept.append({"front": clip(front, 400), "back": clip(with_authority(back, concept), 1200)})
    return kept[:limit], dropped


def clean_question(payload, concept: dict) -> tuple:
    """(question, why_not) — one applied problem with its stappenplan and model answer."""
    q = (payload or {}).get("question") if isinstance(payload, dict) else None
    if not isinstance(q, dict):
        return None, "the reply carried no question"
    why = bad_text(q.get("question", "")) or bad_text(q.get("model", ""))
    text, model = plain(q.get("question", "")), plain(q.get("model", ""))
    steps = [plain(x) for x in (q.get("steps") or []) if str(x).strip()][:8]
    if why:
        return None, f"the problem had {why}"
    if echoes(text, model):
        return None, "the model answer only repeated the problem"
    if len(text) < 40:
        return None, "the problem had no facts"
    if len(model) < 60:
        return None, "the problem came without a model answer"
    if len(steps) < 2:
        return None, "the problem came without a stappenplan to mark against"
    if not citations_ok(text + " " + model + " " + " ".join(steps), concept):
        return None, "the problem cited an authority the concept does not carry"
    other = foreign_case(text + " " + model + " " + " ".join(steps), concept)
    if other:
        return None, f"the problem relied on a case other than its source ({other})"
    slip = doctrine_slip(text + " " + model + " " + " ".join(steps))
    if slip:
        return None, f"the problem had a doctrine slip ({slip})"
    return {"question": clip(text, 2000), "steps": steps, "model": clip(with_authority(model, concept), 4000)}, ""


_CASE_NO = re.compile(r"(?i)(?:\bcase\s+|\bC[-\u2011]\s*)(\d{1,4})\s*/\s*(\d{2,4})\b")


def _case_key(num: str, yr: str) -> tuple:
    return (str(int(num)), yr[-2:])


def own_case(source_name: str):
    """The (number, yy) a source file's own name carries ('marshall-152-84.html' -> ('152','84')), or None."""
    m = re.search(r"(?<![\d])(\d{1,4})[ _/-](\d{2})(?![\d])", re.sub(r"(?i)\.(html?|xhtml|pdf|txt|docx?)$", "", str(source_name or "")))
    return _case_key(*m.groups()) if m else None


def foreign_case(text: str, concept: dict) -> str:
    """A case number in this text other than the judgment the concept was read from ('' when none, or when the
    source's name carries no case number). A judgment cites other cases; a card on it must be about its own."""
    own = own_case(concept.get("source_name", ""))
    if not own:
        return ""
    joined = bool(re.search(r"(?i)joined cases", str(text or "")))
    for num, yr in _CASE_NO.findall(str(text or "")):
        key = _case_key(num, yr)
        if key != own and not (joined and key[1] == own[1]):   # "Joined Cases C-267/91 and C-268/91": one judgment, two numbers
            return f"Case {num}/{yr}"
    return ""


# ---------------------------------------------------------------- doctrine slips (deck Must 6)
# A model that has the right concept in front of it still drifts into the classic wrong sentence. These are the
# ones this course's holdings rule out; an item that says one is dropped and counted as skipped, never shown.
_SENT = re.compile(r"(?<=[.!?])\s+")
_DOCTRINE_SLIPS = (
    ("national law called invalid or void (under primacy it is inapplicable and set aside)",
     re.compile(r"(?i)\b(national|domestic|member state)\b[^.?!]{0,90}\b(act|law|statute|legislation|provision|rule|decree)\b[^.?!]{0,60}\b(is|are|was|were|be|being|become|becomes)\s+(also\s+)?(invalid|void|null|annulled)\b"
               r"|\b(act|statute|decree)\b[^.?!]{0,40}\b(is|was)\s+(invalid|void|null|annulled)\b")),
    ("direct applicability credited to a judgment (it is the Treaty's rule for regulations)",
     re.compile(r"(?i)direct(ly)?[ -]applicab\w*[^.?!]{0,70}\b(establish\w*|creat\w*|introduc\w*|originat\w*|laid down)\b[^.?!]{0,60}\b(simmenthal|van gend|costa)\b"
                r"|\b(simmenthal|van gend|costa)\b[^.?!]{0,60}\b(establish\w*|creat\w*|introduc\w*|laid down)\b[^.?!]{0,60}direct(ly)?[ -]applicab\w*")),
    ("industrial and commercial property called a mandatory requirement (it is an Article 36 ground)",
     re.compile(r"(?i)(industrial (and|or) commercial property|intellectual property|geographical indications?)[^.?!]{0,120}\b(mandatory|overriding|imperative) (requirements?|reasons?)\b")),
    ("primacy credited to Simmenthal (it is Costa v ENEL; Simmenthal adds the duty to set aside)",
     re.compile(r"(?i)\b(primacy|precedence|supremacy)\b[^.?!]{0,80}\b(established|created|introduced|laid down|originated)\b[^.?!]{0,20}\b(in|by)\s+simmenthal\b")),
    ("Van Gend used as the authority for direct effect of a directive",
     re.compile(r"(?i)\bdirectives?\b[^.?!]{0,200}\bvan gend\b|\bvan gend\b[^.?!]{0,200}\bdirectives?\b")),
    ("Keck said to overrule Dassonville",
     re.compile(r"(?i)\bkeck\b[^.?!]{0,40}\b(overrul\w*|overturn\w*|replac\w*)\b[^.?!]{0,30}\bdassonville\b")),
    ("directives given horizontal direct effect",
     re.compile(r"(?i)\bdirectives?\b[^.?!]{0,60}\bhave\b[^.?!]{0,20}\bhorizontal (direct )?effect\b(?![^.?!]{0,20}\bnot\b)")),
)


def doctrine_slip(text: str) -> str:
    """The first known doctrine slip in this text, or ''. Sentences that deny the slip ("not invalid") pass."""
    if re.search(r"(?i)\bcosta\b", text or "") and not re.search(r"(?i)simmenthal", text or "") \
            and re.search(r"(?i)\b(set(ting)? aside|disappl\w*|of its own motion|leave unapplied|refus\w* to apply)\b", text or ""):
        return "the duty to set aside credited to Costa (it is Simmenthal's holding)"
    low = str(text or "").lower()
    if re.search(r"\b(primacy|precedence|supremacy)\b", low) and "simmenthal" in low and "costa" not in low \
            and re.search(r"\b(establish\w*|origin\w*|first|which (case|authority|judgment)|who (laid|created))\b", low) \
            and not re.search(r"\b(not|never)\b[^.?!]{0,30}\b(establish\w*|origin\w*)", low):
        return "primacy credited to Simmenthal (it is Costa v ENEL; Simmenthal adds the duty to set aside)"
    if "spirit" in low and "general scheme" in low and "wording" in low and "direct effect" in low \
            and re.search(r"\b(conditions?|criteria|criterion|test|limbs?|requirements?|rule for ascertaining)\b", low) \
            and not re.search(r"\b(interpret\w*|method|read|approach|teleolog\w*)\b", low):
        return "the Court's way of reading the Treaty (spirit, scheme, wording) given as the conditions for direct effect"
    for sent in _SENT.split(str(text or "")):
        if re.search(r"(?i)\b(not|never|rather than|instead of|no longer|neither)\b[^.?!]{0,30}\b(invalid|void|null|annulled|directly applicable|direct applicability|overrul\w*|horizontal|an? (mandatory|overriding|imperative))", sent):
            continue
        for why, rx in _DOCTRINE_SLIPS:
            if rx.search(sent):
                return why
    return ""


# ---------------------------------------------------------------- second reader (deck Must 6)
# The cheap model writes; a stronger one reads what it wrote before anything is saved. It sees the concept as the
# course stated it plus the doctrine notes, and may only mark an item as wrong, never rewrite it.
REVIEW_RULES = """You check revision material that a law student will study, before he sees it.

You are given one concept as his course stated it, then the cards and the applied problem written from it.
Mark an item wrong ONLY if one of these is true:
- it states the law differently from the concept or from the doctrine notes below;
- it credits a case with a holding that belongs to another case, or cites a case or article for something it does not decide;
- its model answer reaches a conclusion the facts do not support, skips a step the problem asks for, or contradicts itself;
- its facts are absurd or make the rule's real shape impossible (a rule about one thing applied to another);
- its model answer applies a rule without checking an element the rule needs (for example, a claim of sex discrimination
  where the facts show the same rule for men and women), or the concept is not the real issue the facts raise;
- it is not a question and an answer, or an answer is cut off.
Do not mark an item for style, length or because you would phrase it differently.

Return ONLY JSON: {"cards": [{"i": 0, "ok": true, "why": ""}], "problem": {"ok": true, "why": ""}}
`i` is the card's position in the list given. `why` is one short sentence when ok is false.
"""


def review_brief(concept: dict, cards: list, question) -> str:
    return json.dumps({"concept": {k: concept.get(k) for k in ("name", "statement", "authority", "limbs", "traps")},
                       "cards": [{"i": i, "front": c["front"], "back": c["back"]} for i, c in enumerate(cards)],
                       "problem": ({"question": question["question"], "steps": question["steps"], "model": question["model"]} if question else None)},
                      ensure_ascii=False)


def apply_review(payload, cards: list, question) -> tuple:
    """(cards, question, dropped) after the second reader. A reply that cannot be read keeps nothing it did not clear:
    cards stay (they already passed the rules), the problem is held back, and the line says why."""
    if not isinstance(payload, dict):
        return cards, None, ["the problem was held back: its second reading could not be read"] if question else []
    verdict = {}
    for r in payload.get("cards") or []:
        if isinstance(r, dict) and isinstance(r.get("i"), int):
            verdict[r["i"]] = r
    kept, dropped = [], []
    for i, c in enumerate(cards):
        r = verdict.get(i) or {}
        if r.get("ok") is False:
            dropped.append(f"a card the second reader marked wrong ({str(r.get('why') or '')[:120]}): {c['front'][:60]}")
        else:
            kept.append(c)
    if question:
        pr = payload.get("problem") if isinstance(payload.get("problem"), dict) else None
        if pr is None:
            dropped.append("the problem was held back: its second reading could not be read")
            question = None
        elif pr.get("ok") is False:
            dropped.append(f"the problem the second reader marked wrong ({str(pr.get('why') or '')[:120]})")
            question = None
    return kept, question, dropped


# ---------------------------------------------------------------- the deck result line (deck Must 3, 8)
AI_LABEL = "AI-generated from your course files. Verify against your materials."


def _reason(entry: str) -> str:
    """'Keck: the reply was not JSON' -> 'the reply was not JSON'. Detail in a trailing '(...)' is for the log, not the line."""
    r = (entry.split(": ", 1)[1] if ": " in entry else entry).strip()
    k = r.find(" (")
    if k >= 12:
        r = r[:k]
    return clip(r, 110)


def _is_side_issue(entry: str) -> bool:
    r = _reason(entry).lower()
    return "side issue" in r or "quote is not in the material" in r or "found nothing it could quote" in r


def deck_line(*, built: dict, deck_cards: int, deck_problems: int, skipped=(), pending_concepts: int = 0,
              pending_files: int = 0, failed_weeks=(), unreadable=(), nothing_new: bool = False) -> str:
    """One honest sentence-set for the result line. `built` maps week -> (cards, problems) made THIS click;
    deck_* are what exists in the course after it (an API count, not an estimate). It never says "Built" alone
    when anything was skipped, failed or left, and it says "Built nothing" when nothing was built."""
    made_c = sum(c for c, _ in built.values())
    made_q = sum(q for _, q in built.values())
    side = [e for e in skipped if _is_side_issue(e)]            # left out on purpose: a side issue, or no sentence to quote
    rejected = [e for e in skipped if not _is_side_issue(e)]    # written or read, then refused by a check
    trouble = bool(rejected or failed_weeks or unreadable or pending_concepts or pending_files)
    parts = []
    if nothing_new:
        parts.append("Nothing new to build: every file is already read and nothing is waiting.")
    elif not made_c and not made_q:
        parts.append("Built nothing new; your deck is unchanged." if (deck_cards or deck_problems) else "Built nothing.")
    else:
        per = ", ".join(f"week {w}: {c} cards, {q} problems" for w, (c, q) in sorted(built.items()) if c or q)
        parts.append(("Built (" if not trouble else "Partly built (") + per + ").")
    parts.append(f"Deck now: {deck_cards} cards, {deck_problems} problems.")
    if failed_weeks:
        parts.append("Failed: " + "; ".join(failed_weeks) + ".")
    if unreadable:
        parts.append("Not read: " + "; ".join(unreadable) + ".")
    for label, group in (("skipped", rejected), ("left out as side issues or unquotable", side)):
        if not group:
            continue
        why = {}
        for e in group:
            why[_reason(e)] = why.get(_reason(e), 0) + 1
        top = "; ".join(f"{r} ({n})" if n > 1 else r for r, n in sorted(why.items(), key=lambda kv: -kv[1])[:2])
        parts.append(f"{len(group)} {label}: {top}.")
    left = []
    if pending_concepts:
        left.append(f"{pending_concepts} concept{'s' if pending_concepts != 1 else ''}")
    if pending_files:
        left.append(f"{pending_files} file{'s' if pending_files != 1 else ''} still to read")
    if left:
        parts.append(" and ".join(left) + " left, press again to build them.")
    return " ".join(parts)


REVIEW_RULES += "\nDoctrine notes:\n" + DOCTRINE_NOTES
