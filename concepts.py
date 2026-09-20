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
MAX_STATEMENT = 400
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
  "quote": "the exact sentence from the material that states this, copied character for character",
  "confusable_with": ["Cassis de Dijon", "Keck"]
 }]}

Rules:
- Work only from the material given. If it does not teach a concept, do not list it.
- `quote` must be copied from the material exactly. It is checked. A concept whose quote is not found
  is thrown away, so paraphrasing there costs you the whole entry.
- `authority` only if the material names one. Never construct a case number or an article.
- `traps` are mistakes a student actually makes on this concept, from the material's own warnings.
- `method_tag` is the reasoning at work, in two or three words, so the same reasoning can be
  recognised in another course: proportionality, direct effect, remedies, burden of proof, formation,
  transfer of title.
- At most %d concepts, the ones an exam would actually test.
""" % MAX_CONCEPTS


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def grounded(quote: str, haystack: str) -> bool:
    """Is this quote really in the material? Whitespace and case are forgiven; wording is not."""
    q = _norm(quote)
    if len(q) < QUOTE_MIN:
        return False
    return q in _norm(haystack)


def clean(candidate: dict, material: str) -> dict:
    """One model candidate to a saveable concept, or {} when it fails a rule."""
    if not isinstance(candidate, dict):
        return {}
    name = re.sub(r"\s+", " ", str(candidate.get("name", "") or "")).strip(" .,;:\"'")[:MAX_NAME]
    statement = re.sub(r"\s+", " ", str(candidate.get("statement", "") or "")).strip()[:MAX_STATEMENT]
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
    }


def parse(payload, material: str) -> tuple:
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
    for raw in items[:MAX_CONCEPTS * 2]:
        got = clean(raw, material)
        if not got:
            name = (raw or {}).get("name", "?") if isinstance(raw, dict) else "?"
            dropped.append(f"{name}: its quote is not in the material")
            continue
        key = _norm(got["name"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(got)
    return kept[:MAX_CONCEPTS], dropped


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

The question is one applied problem, in the shape a two-hour written exam uses:
- Short facts with named parties that force the concept to be used, not recited.
- `steps` is the stappenplan the answer must walk: the checkpoints a marker looks for, in order.
- `model` is the answer written the way a good student would, naming the authority at the right step.
- Where the concept has limbs, at least one limb must be genuinely contestable on your facts. A
  problem whose answer is obvious at every step teaches nothing.
"""

CITE = re.compile(r"(?i)\b(C[-\u2011]\d{1,4}/\d{2,4}|ECLI:[A-Z:0-9.]+|Art(?:icle)?\.?\s*\d+[a-z]?(?:\(\d+\))?)\b")


def citations_ok(text: str, concept: dict) -> bool:
    """Every case number and article in generated text must already appear in the concept it came
    from. A model that reaches for another authority is reaching past the material, which is the
    failure this whole layer exists to prevent."""
    known = _norm(" ".join([concept.get("statement", ""), concept.get("authority", ""),
                            " ".join(concept.get("limbs") or []), " ".join(concept.get("traps") or []),
                            concept.get("name", "")]))
    for found in CITE.findall(text or ""):
        token = _norm(found).replace("article", "art").replace(".", "").replace(" ", "")
        if token not in known.replace("article", "art").replace(".", "").replace(" ", ""):
            return False
    return True


def clean_cards(payload, concept: dict, limit: int = 3) -> tuple:
    """(cards, dropped) — each card a {front, back} that cites nothing the concept did not."""
    items = (payload or {}).get("cards") if isinstance(payload, dict) else None
    kept, dropped = [], []
    for raw in (items or [])[:limit * 2]:
        if not isinstance(raw, dict):
            continue
        front = re.sub(r"\s+", " ", str(raw.get("front", ""))).strip()
        back = re.sub(r"\s+", " ", str(raw.get("back", ""))).strip()
        if len(front) < 8 or len(back) < 8:
            dropped.append("a card with no question or no answer")
            continue
        if not citations_ok(front + " " + back, concept):
            dropped.append(f"a card citing an authority the concept does not carry: {front[:60]}")
            continue
        kept.append({"front": front[:400], "back": back[:1200]})
    return kept[:limit], dropped


def clean_question(payload, concept: dict) -> tuple:
    """(question, why_not) — one applied problem with its stappenplan and model answer."""
    q = (payload or {}).get("question") if isinstance(payload, dict) else None
    if not isinstance(q, dict):
        return None, "the reply carried no question"
    text = re.sub(r"\s+", " ", str(q.get("question", ""))).strip()
    model = re.sub(r"\s+", " ", str(q.get("model", ""))).strip()
    steps = [re.sub(r"\s+", " ", str(x)).strip() for x in (q.get("steps") or []) if str(x).strip()][:8]
    if len(text) < 40:
        return None, "the problem had no facts"
    if len(model) < 60:
        return None, "the problem came without a model answer"
    if len(steps) < 2:
        return None, "the problem came without a stappenplan to mark against"
    if not citations_ok(text + " " + model + " " + " ".join(steps), concept):
        return None, "the problem cited an authority the concept does not carry"
    return {"question": text[:2000], "steps": steps, "model": model[:4000]}, ""
