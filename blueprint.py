"""Exam Blueprint — what a course actually examines, derived from its past papers + syllabus.

Pure analysis helpers: no database, no network. run.py gathers the course's past-exam/mock
files and its applied syllabus, calls the model with RULES, and normalises the reply here. A
blueprint weights each examined topic by its share of the exam, names the question formats and
doctrines that test it, and records which papers it was seen in — so a later slice can point the
tutor and the generators at what the exam rewards. Nothing here writes; applying lives in run.py
under brief['blueprint'] (jsonb — no migration), exactly like the syllabus.

The split mirrors course_brief: the model is the only non-deterministic step, and it is kept out
of this file so every shape rule is unit-tested without a model or a database.
"""

PAPER_CHARS = 24000      # per paper: a paper is a few pages; the cap guards against a whole reader slipping in
TOTAL_CHARS = 90000      # across all papers fed to the model in one pass
MAX_TOPICS = 20          # a course examines a handful of doctrines, not fifty; the cap keeps the map readable
MAX_LIST = 6             # formats / doctrines / seen_in kept per topic
SYLLABUS_CHARS = 8000    # the syllabus is context, not the main signal — past papers lead

BLUEPRINT_KEY = "blueprint"   # where an applied blueprint lives inside courses.brief


class BlueprintError(ValueError):
    """The model's reply could not be read as a blueprint."""


def _line(v, n=200):
    return " ".join(str(v if v is not None else "").split())[:n]


def _items(v, n=MAX_LIST):
    """A clean, de-duplicated, capped list of short strings from a string or a list."""
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = []
    for x in v:
        s = _line(x, 80)
        if s and s.lower() not in [o.lower() for o in out]:
            out.append(s)
    return out[:n]


def _weight(v):
    """A 0–100 integer; anything unparseable is 0 (it drops out when weights are renormalised)."""
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _conf(v):
    s = str(v if v is not None else "").strip().lower()
    return s if s in ("high", "medium", "low") else "medium"


RULES = """You are an exam analyst for a single university course. You are given the course's past exam papers and mock exams (the strongest signal), and possibly its syllabus, exam format and marking method.

Report, as JSON, what this course actually EXAMINES — not everything it teaches. Weight by what recurs in the papers; the syllabus only fills in topics the papers have not yet shown, at lower confidence.

Return ONE JSON object, no prose around it:
{
  "topics": [
    {
      "topic": "short name of an examined doctrine or theme",
      "weight": integer 0-100, this topic's share of the exam (all weights should roughly sum to 100),
      "formats": ["how it is tested — e.g. IRAC case, essay, short answer, compare"],
      "doctrines": ["the articles, tests or cases it turns on"],
      "seen_in": ["which papers you saw it in, by name"],
      "confidence": "high | medium | low",
      "note": "one sentence on how it tends to be asked"
    }
  ],
  "exam_format": "one line on the paper's shape (number and kind of questions, time, word limits)",
  "method": "one line on the answer method the course rewards, if evident",
  "note": "one line on anything the weighting cannot capture (e.g. only one paper available)"
}

Rules:
- Base weight on frequency and prominence across the papers. A topic in every paper outranks one seen once.
- Prefer 6–12 real topics over a long thin list. Merge near-duplicates.
- If you have no papers, derive provisional topics from the syllabus and mark every confidence "low".
- Name doctrines concretely (e.g. "Art 34 TFEU", "Cassis mandatory requirements"), never vaguely.
- Invent nothing that is not in the material. An empty topics list is a valid answer."""


def build_context(papers, syllabus_block="", exam_format="", method=""):
    """Assemble the user message: brief context first, then the papers (the signal), capped.

    `papers` is a list of {"name", "text"}. Papers are truncated per-paper and in total so a large
    course cannot blow the token budget; the earliest papers in the list win the remaining room.
    """
    parts = []
    if exam_format:
        parts.append("EXAM FORMAT (from the course brief):\n" + _line(exam_format, 600))
    if method:
        parts.append("METHOD the course marks by:\n" + _line(method, 600))
    if syllabus_block:
        parts.append("SYLLABUS (what the course teaches — context, weaker signal than the papers):\n"
                     + syllabus_block[:SYLLABUS_CHARS])
    used = 0
    body = []
    for p in papers or []:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        room = min(PAPER_CHARS, TOTAL_CHARS - used)
        if room <= 0:
            break
        chunk = text[:room]
        used += len(chunk)
        body.append('<paper name="%s">\n%s\n</paper>' % (_line(p.get("name"), 120), chunk))
    if body:
        parts.append("PAST PAPERS / MOCKS (weight by what recurs here):\n" + "\n\n".join(body))
    return "\n\n".join(parts)


def normalise_blueprint(raw, source_papers=None):
    """Validate a model (or posted) blueprint into a stable object.

    Weights are renormalised to sum to 100 so the same material always yields the same shares, and
    same-named topics are merged — that is what makes an apply idempotent and the bars honest.
    """
    if raw is None:
        raise BlueprintError("empty blueprint")
    if isinstance(raw, list):
        raw = {"topics": raw}
    if not isinstance(raw, dict):
        raise BlueprintError("blueprint must be an object")
    topics_in = raw.get("topics")
    if topics_in is None:
        topics_in = []
    if not isinstance(topics_in, list):
        raise BlueprintError("topics must be a list")

    merged = {}
    order = []
    for t in topics_in:
        if not isinstance(t, dict):
            continue
        name = _line(t.get("topic") if t.get("topic") is not None else t.get("name"), 120)
        if not name:
            continue
        key = name.lower()
        row = {
            "topic": name,
            "weight": _weight(t.get("weight")),
            "formats": _items(t.get("formats") if t.get("formats") is not None else t.get("format")),
            "doctrines": _items(t.get("doctrines") if t.get("doctrines") is not None else t.get("authorities")),
            "seen_in": _items(t.get("seen_in") if t.get("seen_in") is not None else t.get("papers")),
            "confidence": _conf(t.get("confidence")),
            "note": _line(t.get("note"), 240),
        }
        if key in merged:
            m = merged[key]
            m["weight"] += row["weight"]
            for k in ("formats", "doctrines", "seen_in"):
                m[k] = _items(m[k] + row[k])
            m["note"] = m["note"] or row["note"]
            if row["confidence"] == "high":
                m["confidence"] = "high"
        else:
            merged[key] = row
            order.append(key)
        if len(order) >= MAX_TOPICS:
            break
    topics = [merged[k] for k in order]

    total = sum(t["weight"] for t in topics)
    if total > 0:
        for t in topics:
            t["weight"] = round(t["weight"] * 100 / total)
        drift = 100 - sum(t["weight"] for t in topics)
        if drift:
            max(topics, key=lambda x: x["weight"])["weight"] += drift
    topics.sort(key=lambda t: (-t["weight"], t["topic"].lower()))

    return {
        "topics": topics,
        "exam_format": _line(raw.get("exam_format"), 600),
        "method": _line(raw.get("method"), 600),
        "note": _line(raw.get("note"), 400),
        "source_papers": _items(source_papers if source_papers is not None else raw.get("source_papers"), 30),
    }
