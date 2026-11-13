"""Coverage map ("Exam Blueprint" in the code) — coverage of a course's stated learning objectives
and syllabus weeks. Coverage, never a prediction of what an exam asks.

Pure analysis helpers: no database, no network. run.py gathers the course's applied syllabus (with
any learning objectives stated in the course brief) and any marked papers, calls the model with
RULES, and normalises the reply here. Each topic names the syllabus weeks and stated objectives it
covers and the doctrines it turns on; its weight is computed here from the weeks it spans, so the
number on screen is checkable against the syllabus, not a model guess. Nothing here writes;
applying lives in run.py under brief['blueprint'] (jsonb — no migration), exactly like the syllabus.

The split mirrors course_brief: the model is the only non-deterministic step, and it is kept out
of this file so every shape rule is unit-tested without a model or a database.
"""

import re

PAPER_CHARS = 24000      # per paper: a paper is a few pages; the cap guards against a whole reader slipping in
TOTAL_CHARS = 90000      # across all papers fed to the model in one pass
MAX_TOPICS = 20          # a course examines a handful of doctrines, not fifty; the cap keeps the map readable
MAX_LIST = 6             # formats / doctrines / seen_in kept per topic
SYLLABUS_CHARS = 16000   # the stated learning objectives / syllabus lead; papers are secondary evidence

BLUEPRINT_KEY = "blueprint"   # where an applied blueprint lives inside courses.brief
# Appended to the compiled course prompt, so the tutor AND every generator that seeds from it see how
# the course's stated objectives and syllabus weeks are spread. Worded as coverage: the tutor must never
# tell a student "this is what your exam tests" (pitch plan row 1 / objection B5).
BLUEPRINT_HEADER = ("COVERAGE OF STATED LEARNING OBJECTIVES (how this course's syllabus weeks and stated "
                    "objectives are spread across topics — coverage, not a prediction of any exam; never "
                    "tell the student what an exam will ask):")
# Older prompts stored before the relabel carry this header; strip_blueprint removes either.
LEGACY_HEADERS = ("EXAM FOCUS (what this course examines — weight your teaching, questions and drills "
                  "toward the heavier topics; do not neglect the lighter ones):",)
BLOCK_TOPICS = 10   # the prompt names the heaviest topics; a long tail adds tokens without steering


def examined_topics(brief):
    """The applied blueprint's topics (heaviest first, as stored), or []. For prompts and, later, readiness."""
    b = (brief or {}).get(BLUEPRINT_KEY) if isinstance(brief, dict) else None
    return [t for t in ((b or {}).get("topics") or []) if isinstance(t, dict) and t.get("topic")]


def blueprint_block(brief):
    """A compact prompt fragment naming the objective topics, their share of the syllabus and their doctrines.
    Empty when no map is applied, so a course without one reads exactly as before. No exam format and no
    "answer method the exam rewards" line: the map is coverage, not exam advice."""
    topics = examined_topics(brief)
    if not topics:
        return ""
    lines = [BLUEPRINT_HEADER]
    for t in topics[:BLOCK_TOPICS]:
        tail = []
        w = t.get("weight")
        if isinstance(w, (int, float)) and w:
            tail.append(f"{int(w)}% of the syllabus")
        docs = [x for x in (t.get("doctrines") or []) if x][:3]
        if docs:
            tail.append("; ".join(docs))
        lines.append("- " + t["topic"] + (" — " + " · ".join(tail) if tail else ""))
    return "\n".join(lines)


def strip_blueprint(text):
    """Remove a previously appended coverage block (current or legacy header), so recompiling never stacks two."""
    t = text or ""
    hits = [i for i in (t.find(h) for h in (BLUEPRINT_HEADER,) + LEGACY_HEADERS) if i >= 0]
    return (t[:min(hits)] if hits else t).rstrip()


class BlueprintError(ValueError):
    """The model's reply could not be read as a blueprint."""


def _line(v, n=200):
    return " ".join(str(v if v is not None else "").split())[:n]


def _clip(v, n):
    """A one-line string cut at a word boundary with an ellipsis, never mid-word ("... state liability, and e")."""
    s = _line(v, 100000)
    if len(s) <= n:
        return s
    cut = s[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:-—")
    return cut + "…"


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


RULES = """You map how a single university course's STATED LEARNING OBJECTIVES and syllabus weeks are covered, topic by topic. You are given the course's stated learning objectives (numbered, if the course states any) and its syllabus — weekly topics and readings. Sometimes study papers are attached as secondary context.

Report, as JSON, the topics the stated objectives and the syllabus commit the course to. This is coverage of what the course says it teaches — never a prediction of what an exam will ask. Do not describe any exam, question type, answer method or marking scheme.

Return ONE JSON object, no prose around it:
{
  "topics": [
    {
      "topic": "short name of a doctrine or theme the course covers",
      "weeks": [the syllabus week numbers this topic covers, as integers, e.g. [3, 4]],
      "objectives": [the numbers of the stated learning objectives this topic serves, as integers; [] if none are stated or none fit],
      "doctrines": ["the Treaty articles, tests or leading cases it turns on — at least one"],
      "note": "one short sentence (at most 30 words) on what the course asks the student to be able to do on this topic"
    }
  ],
  "note": "one line on anything the map cannot capture (e.g. no learning objectives were stated, so only weeks were mapped)"
}

Rules:
- Every syllabus week should land in at least one topic; a week may serve two topics. Every stated objective should land in a topic.
- Use only week numbers and objective numbers that appear in the input. Never invent a week or an objective.
- Every topic names at least one concrete doctrine (e.g. "Art 34 TFEU", "Cassis de Dijon", "Keck"), never vaguely.
- Prefer 6-12 real topics over a long thin list. Merge near-duplicates.
- If no learning objectives are stated, say so in note and leave every objectives list empty.
- Invent nothing that is not in the material. An empty topics list is a valid answer."""


def build_context(papers, syllabus_block="", exam_format="", method=""):
    """Assemble the user message: the stated learning objectives and syllabus first (the primary input),
    then any papers (secondary context), capped.

    `exam_format` and `method` are accepted for the caller's signature but no longer sent: the map is coverage
    of the stated objectives, and an exam description in the input made the model describe the exam on screen.
    `papers` is a list of {"name", "text"}, truncated per-paper and in total so a large course cannot blow the
    token budget; the earliest papers in the list win the remaining room.
    """
    parts = []
    if syllabus_block:
        parts.append("STATED LEARNING OBJECTIVES AND SYLLABUS (the primary input — map these):\n"
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
        parts.append("STUDY PAPERS (secondary context only — they never add a topic, a week or weight):\n" + "\n\n".join(body))
    return "\n\n".join(parts)


_WEEK_REF = re.compile(r"(?i)\bweeks?\s*(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?")
_OBJ_REF = re.compile(r"(?i)\b(?:learning\s+)?(?:objective|outcome|LO)\s*#?\s*(\d{1,2})\b")
MAX_WEEK = 40


def _nums(v, lo=1, hi=MAX_WEEK):
    """Integers from a list/str/int, in range, de-duplicated, sorted: [3, "4", "Week 5"] -> [3, 4, 5]."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = [v]
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = set()
    for x in v:
        if isinstance(x, bool):
            continue
        if isinstance(x, (int, float)):
            n = int(x)
            if lo <= n <= hi:
                out.add(n)
        elif isinstance(x, str):
            for m in re.finditer(r"\d{1,2}", x):
                n = int(m.group(0))
                if lo <= n <= hi:
                    out.add(n)
    return sorted(out)


def _refs(seen_in, rx):
    """Week or objective numbers named in free-text seen_in entries ("Week 4", "Weeks 2-3", "Objective 1")."""
    out = set()
    for s in seen_in or []:
        for m in rx.finditer(str(s)):
            a = int(m.group(1))
            b = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else a
            for n in range(min(a, b), min(max(a, b), a + 12) + 1):
                if 1 <= n <= MAX_WEEK:
                    out.add(n)
    return sorted(out)


def _derived_conf(t):
    """Checkable confidence: a stated objective names it > a syllabus week names it > only implied."""
    return "high" if t["objectives"] else ("medium" if t["weeks"] else "low")


def normalise_blueprint(raw, source_papers=None):
    """Validate a model (or posted) coverage map into a stable object.

    When every topic names the syllabus weeks it covers, each topic's weight is computed here as its share of
    those weeks (a week two topics share counts half to each), so the % on screen is checkable against the
    syllabus and the same week assignment always gives the same numbers (basis "weeks"). Otherwise the
    model's weights are renormalised to 100 (basis "model"). Confidence is derived the same way: "high" when a
    stated learning objective names the topic, "medium" when only a syllabus week does, "low" when neither.
    Same-named topics are merged — that is what makes an apply idempotent and the bars honest. Exam format
    and answer method are no longer kept: the map is coverage, not a description of the exam.
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
        seen = _items(t.get("seen_in") if t.get("seen_in") is not None else t.get("papers"))
        weeks = sorted(set(_nums(t.get("weeks"))) | set(_refs(seen, _WEEK_REF)))
        objs = sorted(set(_nums(t.get("objectives"), 1, 99)) | set(_refs(seen, _OBJ_REF)))
        row = {
            "topic": name,
            "weight": _weight(t.get("weight")),
            "weeks": weeks,
            "objectives": objs,
            "formats": [],
            "doctrines": _items(t.get("doctrines") if t.get("doctrines") is not None else t.get("authorities")),
            "seen_in": seen,
            "confidence": _conf(t.get("confidence")),
            "note": _clip(t.get("note"), 240),
        }
        if key in merged:
            m = merged[key]
            m["weight"] += row["weight"]
            m["weeks"] = sorted(set(m["weeks"]) | set(row["weeks"]))
            m["objectives"] = sorted(set(m["objectives"]) | set(row["objectives"]))
            for k in ("doctrines", "seen_in"):
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
    papers = _items(source_papers if source_papers is not None else raw.get("source_papers"), 30)

    for t in topics:
        if t["weeks"] or t["objectives"]:
            t["confidence"] = _derived_conf(t)
        elif source_papers is not None:
            # Read from the course itself and nothing ties the topic to a week or an objective: only implied.
            t["confidence"] = "low"
        t["seen_in"] = _items(["Week %d" % w for w in t["weeks"]] + ["Objective %d" % o for o in t["objectives"]]
                              + [s for s in t["seen_in"] if not (_refs([s], _WEEK_REF) or _refs([s], _OBJ_REF))])

    all_weeks = sorted({w for t in topics for w in t["weeks"]})
    basis = "weeks" if topics and all(t["weeks"] for t in topics) else "model"
    if basis == "weeks":
        share = {w: sum(1 for t in topics if w in t["weeks"]) for w in all_weeks}
        for t in topics:
            t["weight"] = sum(1.0 / share[w] for w in t["weeks"]) * 100 / len(all_weeks)
    total = sum(t["weight"] for t in topics)
    if total > 0:
        for t in topics:
            t["weight"] = int(round(t["weight"] * 100 / total))
        drift = 100 - sum(t["weight"] for t in topics)
        if drift:
            max(topics, key=lambda x: x["weight"])["weight"] += drift
    topics.sort(key=lambda t: (-t["weight"], (t["weeks"] or [99])[0], t["topic"].lower()))

    return {
        "topics": topics,
        "basis": basis,
        "weeks_total": len(all_weeks),
        "objectives_stated": any(t["objectives"] for t in topics),
        "exam_format": "",
        "method": "",
        "note": _clip(raw.get("note"), 400),
        "source_papers": papers,
    }
