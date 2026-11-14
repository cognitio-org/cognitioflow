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

import contextvars
import hashlib
import json
import re
import time

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
BLOCK_TOPICS = 20   # = MAX_TOPICS: a per-week map has a topic per week; cutting at 10 dropped weeks 11-12 (w4)


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
            unit = "the stated learning objectives" if t.get("share_unit") == "objectives" else "the syllabus"
            tail.append(f"{int(w)}% of {unit}")
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


RULES = """You map a university course's syllabus weeks to its STATED LEARNING OBJECTIVES and name the legal authorities each week turns on. You are given the syllabus (numbered weeks with their topics) and, if the course states any, its numbered learning objectives. This is coverage of what the course says it teaches — never a prediction of what an exam will ask. Do not describe any exam, question type, answer method or marking scheme.

Return ONE JSON object, no prose around it, in exactly this shape:
{"weeks": [{"week": 1, "lo": [1], "law": ["Art 34 TFEU", "Dassonville", "Cassis de Dijon"]}]}

Rules:
- One entry for every syllabus week in the input, in week order. Use only week numbers and objective numbers that appear in the input. Never invent a week or an objective.
- lo: the numbers of the stated learning objectives the week serves (usually one); [] if no objectives are stated.
- law: 2 to 4 authorities that week's topics turn on (at least one, never vaguely): first the Treaty article(s), then the leading CJEU judgments in date order. Name each judgment by its usual short name as written in the case title (e.g. "Dassonville", "Cassis de Dijon", "Keck and Mithouard", "N.S. and M.E."). No duplicates, no descriptions.
- If the input has no syllabus weeks, return instead one entry per stated objective: {"objectives": [{"lo": 1, "law": ["..."]}]}.
- Invent nothing that is not in the material. An empty list is a valid answer."""


# The syllabus weeks and stated objectives the map is checked against. build_context reads them from the block it
# is given and leaves them here for the normalise_blueprint call that follows in the same request (run.py's extract
# calls the two back to back); explicit arguments to normalise_blueprint always win. A ContextVar, not a global:
# each request runs in its own copied context, so one course's scope never leaks into another's.
_SCOPE = contextvars.ContextVar("blueprint_scope", default=None)
_BLOCK_WEEK = re.compile(r"(?m)^Week\s+(\d{1,2})\b")
_BLOCK_OBJ = re.compile(r"(?m)^Objective\s+(\d{1,2}):\s*(.*)$")


def scope_from_block(syllabus_block):
    """(syllabus week numbers, stated objective texts) named in course_brief.syllabus_block's output."""
    text = syllabus_block or ""
    weeks = sorted({int(m.group(1)) for m in _BLOCK_WEEK.finditer(text) if 1 <= int(m.group(1)) <= MAX_WEEK})
    objs = [m.group(2).strip() for m in _BLOCK_OBJ.finditer(text)]
    return weeks, objs


_BLOCK_WEEK_LINE = re.compile(r"(?m)^Week\s+(\d{1,2})\b(.*)$")


def weeks_from_block(syllabus_block):
    """{week number: {"title", "topics"}} as course_brief.syllabus_block wrote them ("Week 3 — Title. Topics: a; b.
    Reading: c."). The coverage map names its topics after the course's own weeks, so these are the course's words."""
    out = {}
    for m in _BLOCK_WEEK_LINE.finditer(syllabus_block or ""):
        n = int(m.group(1))
        if not 1 <= n <= MAX_WEEK or n in out:
            continue
        rest = m.group(2).strip()
        rest = re.split(r"\.\s+Reading:\s", rest, maxsplit=1)[0]
        title, _, topics = rest.partition(". Topics: ")
        if not _ and title.startswith("Topics: "):
            title, topics = "", title[len("Topics: "):]
        title = title.lstrip("—–- ").strip().rstrip(".")
        out[n] = {"title": _line(title, 120),
                  "topics": [_line(x, 120) for x in topics.rstrip(".").split("; ") if x.strip()]}
    return out


def build_context(papers, syllabus_block="", exam_format="", method=""):
    """Assemble the user message: the stated learning objectives and the syllabus — nothing else.

    `papers`, `exam_format` and `method` are accepted for the caller's signature but no longer sent: the map is
    coverage of the stated objectives and syllabus weeks. Past papers in the input pulled the model toward
    describing the exam, and they can never add a topic, a week or a weight anyway. Also records the known weeks
    and objectives (see _SCOPE) so the reply is checked against them.
    """
    _SCOPE.set(scope_from_block(syllabus_block) + (weeks_from_block(syllabus_block),))
    if not syllabus_block:
        return ("No syllabus weeks and no learning objectives are stated for this course. Return "
                '{"topics": [], "note": "No syllabus weeks or learning objectives were stated."}')
    return ("STATED LEARNING OBJECTIVES AND SYLLABUS (the only input — map these):\n"
            + syllabus_block[:SYLLABUS_CHARS])


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
    """Checkable confidence: mapped to a stated objective > mapped to a syllabus week > only implied."""
    return "high" if t["objectives"] else ("medium" if t["weeks"] else "low")


def _r2(x):
    return round(float(x) + 1e-9, 2)


def _first(d, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d.get(k)
    return None


# ---------------------------------------------------------------- the demo course's written authority chips
# The coverage map's authority chips (Treaty articles, case names) used to come from the model, and the same inputs
# gave different chips on different builds ("Art 19 TFEU" does not exist; "Art 260" came and went). For the demo
# course they are WRITTEN, one row per demo-schedule week, like the demo's learning objectives: from the public
# sources in docs/demo (Treaty text on EUR-Lex, Court of Justice judgments). The model keeps only which objectives
# a week serves. Each chip is a dict so tests/test_blueprint_authorities.py can check it against
# docs/demo/eu-demo-sources-index.json: a case as the triple (name, case number, ECLI), an article for existence in
# the consolidated TFEU and against the proposition it may be cited for. A course that is not the demo course gets
# no table: its chips stay whatever the model names.
_A = lambda n, why: {"chip": "Art %d TFEU" % n, "kind": "article", "article": n, "treaty": "TFEU", "for": why}
_C = lambda chip, name, num, ecli: {"chip": chip, "kind": "case", "name": name, "number": num, "ecli": ecli}
_W34 = "the prohibition of import restrictions and measures of equivalent effect"
_W36 = "the derogation grounds"
_DASSONVILLE = _C("Dassonville (Case 8/74)", "Dassonville", "Case 8/74", "ECLI:EU:C:1974:82")
_CASSIS = _C("Cassis de Dijon (Case 120/78)", "Cassis de Dijon", "Case 120/78", "ECLI:EU:C:1979:42")
_KECK = _C("Keck and Mithouard (C-267/91 and C-268/91)", "Keck and Mithouard", "Joined Cases C-267/91 and C-268/91",
           "ECLI:EU:C:1993:905")
_ITALY = _C("Commission v Italy, trailers (C-110/05)", "Commission v Italy", "Case C-110/05", "ECLI:EU:C:2009:66")
_KER = _C("Ker-Optika (C-108/09)", "Ker-Optika", "Case C-108/09", "ECLI:EU:C:2010:725")
_VGL = _C("Van Gend en Loos (Case 26/62)", "Van Gend en Loos", "Case 26/62", "ECLI:EU:C:1963:1")
_COSTA = _C("Costa v ENEL (Case 6/64)", "Costa v ENEL", "Case 6/64", "ECLI:EU:C:1964:66")
_SIMM = _C("Simmenthal (Case 106/77)", "Simmenthal", "Case 106/77", "ECLI:EU:C:1978:49")
_MARSHALL = _C("Marshall (Case 152/84)", "Marshall", "Case 152/84", "ECLI:EU:C:1986:84")

#: week title (as written in docs/demo/eu-public-demo-course.json) -> its authorities, in the order they are shown:
#: Treaty articles first, then judgments in date order.
DEMO_AUTHORITIES = {
    "Articles 34 to 36 TFEU: the prohibition and its derogations": [
        _A(34, _W34), _A(35, "the prohibition of export restrictions and measures of equivalent effect"), _A(36, _W36)],
    "Dassonville and Cassis de Dijon: the broad MEQR test and mutual recognition": [_A(34, _W34), _DASSONVILLE, _CASSIS],
    "Keck: product requirements and selling arrangements": [_A(34, _W34), _KECK],
    "Market access and use restrictions: Commission v Italy (trailers)": [_A(34, _W34), _A(36, _W36), _ITALY],
    "Internet sales and justification: Ker-Optika": [_A(34, _W34), _A(36, _W36), _ITALY, _KER],
    "Solving a free-movement-of-goods problem question": [_A(34, _W34), _A(36, _W36), _DASSONVILLE, _KECK, _KER],
    "Direct effect: Van Gend en Loos and the preliminary reference": [
        _A(267, "the preliminary reference procedure"), _VGL],
    "Primacy: Costa v ENEL and Simmenthal": [_COSTA, _SIMM],
    "Directives: Marshall and the limits of direct effect": [
        _A(288, "the legal effect of directives"), _A(267, "the preliminary reference procedure"), _MARSHALL],
}
_BY_TITLE = {re.sub(r"\s+", " ", k).strip().lower(): v for k, v in DEMO_AUTHORITIES.items()}


def curated_chips(week_title):
    """The written authority chips for a demo-schedule week, or None when the week is not one of them."""
    rows = _BY_TITLE.get(re.sub(r"\s+", " ", str(week_title or "")).strip().lower())
    return [r["chip"] for r in rows] if rows else None


def _from_units(raw, known_weeks, objective_texts, week_info):
    """The model's per-week (or, without a syllabus, per-objective) reply as topics. The topic names and notes come
    from the course's own syllabus, never from the model: the model only says which objectives a week serves and
    which authorities it turns on. That keeps the map in the course's words (a model note once claimed an Art 102
    exemption) and makes the same inputs give the same map. Every syllabus week becomes a topic, also one the
    reply left out."""
    rows = []
    if isinstance(raw.get("weeks"), list):
        by_week = {}
        for u in raw["weeks"]:
            if isinstance(u, dict):
                n = _nums(_first(u, "week", "w"))
                if n and n[0] not in by_week:
                    by_week[n[0]] = u
        order = sorted(set(by_week) | set(known_weeks or []))
        if known_weeks is not None:
            order = [n for n in order if n in known_weeks]
        names = set()
        for n in order:
            u, info = by_week.get(n, {}), (week_info or {}).get(n) or {}
            name = info.get("title") or "Week %d" % n
            if name.lower() in names:
                name = "%s (week %d)" % (name, n)
            names.add(name.lower())
            topics = info.get("topics") or []
            # The demo course's authority chips are written, not asked for (blueprint_authorities); any other
            # course keeps what the model named.
            written = curated_chips(info.get("title"))
            rows.append({"topic": name, "weeks": [n], "objectives": _first(u, "lo", "objectives") or [],
                         "doctrines": written if written is not None else (_first(u, "law", "doctrines") or []),
                         "note": ("Covers " + "; ".join(topics) + ".") if topics else ""})
    elif isinstance(raw.get("objectives"), list):
        seen = set()
        for u in raw["objectives"]:
            if not isinstance(u, dict):
                continue
            n = _nums(_first(u, "lo", "objective"), 1, 99)
            if not n or n[0] in seen or (objective_texts and n[0] > len(objective_texts)):
                continue
            seen.add(n[0])
            txt = objective_texts[n[0] - 1] if objective_texts and n[0] <= len(objective_texts) else ""
            rows.append({"topic": _clip(txt, 90) or "Objective %d" % n[0], "weeks": [], "objectives": [n[0]],
                         "doctrines": _first(u, "law", "doctrines") or [], "note": ""})
        rows.sort(key=lambda r: r["objectives"][0])
    return {"topics": rows, "note": raw.get("note") or ""}


def _tidy_doctrines(items):
    """Authority chips as a professor reads them: capitalised, and no chip that only repeats part of another one
    ("Gebhard" beside "Gebhard test", "golden shares" beside "Commission v Portugal (golden shares)")."""
    out = [(x[:1].upper() + x[1:]) if x[:1].islower() else x for x in items]
    keep = []
    for i, x in enumerate(out):
        rx = re.compile(r"(?<![\w])" + re.escape(x.lower()) + r"(?![\w])")
        if any(j != i and len(y) > len(x) and rx.search(y.lower()) for j, y in enumerate(out)):
            continue
        keep.append(x)
    return keep


_HASH = re.compile(r"^[0-9a-f]{16,64}$")


def normalise_blueprint(raw, source_papers=None, syllabus_weeks=None, objectives=None, week_info=None):
    """Validate a model (or posted) coverage map into a stable object.

    Checked against the course: `syllabus_weeks` (the week numbers the applied syllabus has) and `objectives`
    (the stated learning objectives, as texts or a count). Any week or objective number outside them is dropped —
    the model cannot invent week 30 or objective 9. When not passed they come from the build_context call that
    preceded this one in the same request (extract), or, failing that, are not checked (a re-save of a proposal
    that was already checked).

    The % is computed here, never taken from the model:
      basis "weeks"      — some topic names syllabus weeks: each topic's share is the weeks it spans (a week two
                           topics share counts half to each) out of ALL the course's syllabus weeks, so
                           "2 of 12 weeks" is something a professor can count, and equal weeks give equal %.
                           A topic tied to no week gets no % (it is shown as "not tied to a syllabus week").
      basis "objectives" — no topic names a week but some serve stated objectives: the same, out of the
                           stated objectives.
      basis "model"      — only for maps saved before weeks existed: the stored weights, renormalised to 100.
      basis "none"       — nothing to compute a share from: every weight is 0 and the panel shows no %.
    Weights are rounded per topic and never forced to sum to 100 — forcing the sum is what made 2 of 12 weeks
    read 18% on one topic and 17% on the next. Confidence is derived the same way: "high" when the topic is
    mapped to a stated objective, "medium" when only to a syllabus week, "low" when neither. Same-named topics
    are merged — that makes an apply idempotent and the bars honest.
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

    scope = _SCOPE.get()
    if scope is not None:
        _SCOPE.set(None)          # one build_context checks one reply, never a later unrelated call
    if syllabus_weeks is None and objectives is None and scope is not None:
        syllabus_weeks, objectives = scope[0], scope[1]
    if week_info is None and scope is not None and len(scope) > 2:
        week_info = scope[2]
    scoped = syllabus_weeks is not None or objectives is not None
    known_weeks = sorted({w for w in _nums(syllabus_weeks)}) if syllabus_weeks is not None else None
    if objectives is None:
        n_obj = None
    elif isinstance(objectives, int) and not isinstance(objectives, bool):
        n_obj = max(0, objectives)
    else:
        n_obj = len([o for o in (objectives or []) if str(o).strip()])
    if raw.get("topics") is None and (isinstance(raw.get("weeks"), list) or isinstance(raw.get("objectives"), list)):
        texts = [str(o) for o in objectives] if isinstance(objectives, (list, tuple)) else []
        raw = {**raw, **_from_units(raw, known_weeks, texts, week_info)}
        topics_in = raw["topics"]

    merged = {}
    order = []
    legacy_weight = False
    hint_of = {"weeks": 0, "objectives": 0}
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
        if known_weeks is not None:
            weeks = [w for w in weeks if w in known_weeks]
        if n_obj is not None:
            objs = [o for o in objs if o <= n_obj]
        unit = t.get("share_unit")
        if unit in hint_of:
            hint_of[unit] = max(hint_of[unit], _weight(t.get("share_of")))
        if t.get("weight") and "share_unit" not in t and not t.get("weeks") and not t.get("objectives") \
                and not scoped:
            # a weight stored by the old version (re-saved with no course scope); a fresh build never trusts one
            legacy_weight = True
        row = {
            "topic": name,
            "weight": _weight(t.get("weight")),
            "weeks": weeks,
            "objectives": objs,
            "formats": [],
            "doctrines": _tidy_doctrines(_items(t.get("doctrines") if t.get("doctrines") is not None
                                                else t.get("authorities"))),
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
            m["doctrines"] = _tidy_doctrines(m["doctrines"])
            m["note"] = m["note"] or row["note"]
            if row["confidence"] == "high":
                m["confidence"] = "high"
        else:
            merged[key] = row
            order.append(key)
        if len(order) >= MAX_TOPICS:
            break
    topics = [merged[k] for k in order]

    for t in topics:
        if t["weeks"] or t["objectives"]:
            t["confidence"] = _derived_conf(t)
        else:
            # Nothing ties the topic to a week or an objective: only implied, whatever the stored label said.
            t["confidence"] = "low"
        # Week/objective refs are rebuilt from the validated numbers; free-text refs to dropped ones go too.
        t["seen_in"] = _items(["Week %d" % w for w in t["weeks"]] + ["Objective %d" % o for o in t["objectives"]]
                              + [s for s in t["seen_in"] if not (_refs([s], _WEEK_REF) or _refs([s], _OBJ_REF))])

    mapped_weeks = sorted({w for t in topics for w in t["weeks"]})
    mapped_objs = sorted({o for t in topics for o in t["objectives"]})
    if mapped_weeks:
        basis, field, mapped = "weeks", "weeks", mapped_weeks
        of = len(known_weeks) if known_weeks is not None else max(len(mapped_weeks), hint_of["weeks"])
    elif mapped_objs:
        basis, field, mapped = "objectives", "objectives", mapped_objs
        of = n_obj if n_obj is not None else max(len(mapped_objs), hint_of["objectives"])
    elif legacy_weight and sum(t["weight"] for t in topics) > 0:
        basis, field, mapped, of = "model", None, [], 0
    else:
        basis, field, mapped, of = "none", None, [], 0

    if field:
        holders = {n: sum(1 for t in topics if n in t[field]) for n in mapped}
        for t in topics:
            share = sum(1.0 / holders[n] for n in t[field])
            t["share"] = _r2(share)
            t["share_of"] = of
            t["share_unit"] = field
            t["weight"] = int(round(share * 100 / of + 1e-9)) if of else 0
    elif basis == "model":
        total = sum(t["weight"] for t in topics)
        for t in topics:
            t["weight"] = int(round(t["weight"] * 100 / total + 1e-9))
    else:
        for t in topics:
            t["weight"] = 0
    topics.sort(key=lambda t: (-t.get("share", t["weight"]), (t["weeks"] or [99])[0], (t["objectives"] or [99])[0],
                               t["topic"].lower()))

    return {
        "topics": topics,
        "basis": basis,
        # the real syllabus count when known (the denominator of every %), else the weeks the map names
        "weeks_total": len(known_weeks) if known_weeks is not None else (of if basis == "weeks" else len(mapped_weeks)),
        "weeks_mapped": mapped_weeks,
        "weeks_unmapped": [w for w in (known_weeks or []) if w not in mapped_weeks],
        "objectives_total": n_obj if n_obj is not None else (of if basis == "objectives" else len(mapped_objs)),
        "objectives_mapped": mapped_objs,
        "objectives_stated": bool(n_obj) if n_obj is not None else bool(mapped_objs),
        "exam_format": "",
        "method": "",
        "note": _clip(raw.get("note"), 400),
        "source_papers": [],      # papers are no longer read (build_context); kept for the stored shape
        **({"input_hash": raw["input_hash"]} if _HASH.match(str(raw.get("input_hash") or "")) else {}),
    }


# ---------------------------------------------------------------- a repeatable build (pitch: 20 builds, one map)
#: Part of every input hash: a change to the prompt or to how a reply is read makes an old saved map "different
#: inputs", so Rebuild asks the model again instead of returning a map the new rules would not produce.
PROMPT_VERSION = "coverage-units-2026-11-14-w5"


def input_hash(model, context):
    """sha256 of everything that decides the map: prompt version, RULES, model and the course's syllabus context."""
    blob = json.dumps([PROMPT_VERSION, RULES, model or "", context or ""], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _retryable(e):
    """A refusal (4xx other than 429) is final; a timeout, a 5xx/502, a cut-off or unreadable reply is worth a retry."""
    code = getattr(e, "status_code", None) or getattr(e, "code", None) or getattr(e, "status", None)
    return not (isinstance(code, int) and 400 <= code < 500 and code != 429)


def propose(syllabus_block, ask, *, model, saved=None, fresh=False, attempts=2, pause=1.5, sleep=time.sleep):
    """One coverage-map proposal, repeatable.

    `ask(context) -> parsed JSON` is the model call (run.py sends it at temperature 0, see llm.repeatable_kwargs).
    Same inputs -> same map: when the saved map was built from exactly these inputs (its input_hash), it is
    returned without a model call ("cached": "saved"). `fresh=True` always asks the model. A failed call
    (timeout, 502, cut-off or unreadable reply) is retried once; the last error is raised if every attempt fails,
    and the panel then keeps showing the saved map. The cache lives on the saved map itself (courses.brief), never
    in process memory, so it survives a restart and needs no schema change."""
    ctx = build_context([], syllabus_block=syllabus_block)
    _SCOPE.set(None)
    weeks, objs = scope_from_block(syllabus_block)
    info = weeks_from_block(syllabus_block)
    h = input_hash(model, ctx)
    if not fresh and isinstance(saved, dict) and saved.get("input_hash") == h and saved.get("topics"):
        return {**saved, "cached": "saved", "attempts": 0}
    last = None
    for i in range(max(1, attempts)):
        if i:
            sleep(pause * i)
        try:
            raw = ask(ctx)
            if isinstance(raw, dict):
                raw = {k: v for k, v in raw.items() if k != "input_hash"}
            blu = normalise_blueprint(raw, syllabus_weeks=weeks, objectives=objs, week_info=info)
            return {**blu, "input_hash": h, "cached": "", "attempts": i + 1}
        except Exception as e:  # noqa: BLE001 - classified below; the caller maps the last one to its HTTP reply
            last = e
            if not _retryable(e):
                break
    raise last
