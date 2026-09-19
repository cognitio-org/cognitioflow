"""
Course brief → tutor prompt. Pure functions only: no database, no filesystem outside prompts/.

A brief is the structured description of a course (lecturer, exam, authority order, …). The app compiles it into
courses.tutor_prompt so every course's prompt has the same shape as the original European Law one. Empty fields
render nothing; an entirely empty brief means "keep the stored tutor_prompt".
"""
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"

# (key, label, kind) — kind is "text", "long", "date" or "list". Order is the form order.
BRIEF_FIELDS = [
    ("course_code", "Course code", "text"),
    ("period", "Period", "text"),
    ("lecturer", "Lecturer", "text"),
    ("wg_tutor", "WG tutor", "text"),
    ("textbook", "Textbook", "text"),
    ("exam_format", "Exam format", "long"),
    ("exam_date", "Exam date", "date"),
    ("assessment_weighting", "Assessment weighting", "text"),
    ("permitted_materials", "Permitted materials", "long"),
    ("authority_order", "Authority order", "list"),
    ("method", "Method", "long"),
    ("provenance_tags", "Provenance tags", "list"),
    ("notes", "Notes", "long"),
]
LIST_FIELDS = {k for k, _, kind in BRIEF_FIELDS if kind == "list"}

# Phase 13. The syllabus is not a form field — it is extracted from an uploaded document and applied in one
# step — so it is not in BRIEF_FIELDS (which drives the course dialog and /api/course-meta). It still lives in
# the same brief, under this key, so one JSONB column stays the whole structured description of a course.
SYLLABUS_KEY = "syllabus"
SYLLABUS_HEADER = "COURSE SCHEDULE (from the syllabus):"
MAX_WEEKS = 40          # a teaching block is 6-10; 40 is a wall against a runaway reply, not a real limit
MAX_ITEMS = 20          # topics or readings per week
MAX_LINE = 240          # characters per topic or reading

# The seven Blackstone tab colours (static/index.html TABS) and the book cover. Course accents never reuse them.
TAB_COLOURS = ["#2f5fae", "#d98a2b", "#1f7a4d", "#8fbf6a", "#8e2f6e", "#d46a9a", "#c9b23a"]
BOOK_COVER = "#7a1f22"
# Default accents for new courses: far from every tab colour and the cover, ≥3:1 against both paper colours.
PALETTE = ["#5a7384", "#6a6aa0", "#8a6a3f", "#5e7d6c", "#946b8a", "#a0573f"]

# Seeded on an empty database: (id, name, accent, prompts/<seed>.json)
SEED_COURSES = [
    ("eu", "European Law", "#24467a", "eu_law"),
    ("prop", "Property Law", "#2e6b4a", "property_law"),
]


class BriefError(ValueError):
    pass


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _sentence(t: str) -> str:
    return t if t[-1:] in ".!?" else t + "."


def normalise_brief(raw) -> dict:
    """Validate and tidy a brief from the API. Unknown keys and malformed values raise BriefError."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BriefError("brief must be an object")
    known = {k for k, _, _ in BRIEF_FIELDS} | {SYLLABUS_KEY}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise BriefError(f"unknown brief field(s): {', '.join(unknown)}")
    out = {}
    syllabus = normalise_syllabus(raw.get(SYLLABUS_KEY))
    if syllabus["weeks"]:
        out[SYLLABUS_KEY] = syllabus
    for key, _, kind in BRIEF_FIELDS:
        v = raw.get(key)
        if kind == "list":
            if v is None:
                items = []
            elif isinstance(v, str):
                items = v.splitlines()
            elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                items = v
            else:
                raise BriefError(f"{key} must be a list of strings")
            items = [x.strip() for x in items]
            if key == "authority_order":  # "1. WG notes" pasted from a numbered list → "WG notes"
                items = [re.sub(r"^\d+[.)]\s+", "", x) for x in items]
            if key == "provenance_tags":
                items = [x if x.startswith("[") and x.endswith("]") else f"[{x.strip('[]')}]" for x in items if x.strip("[] ")]
            out[key] = [x for x in items if x]
        else:
            if v is not None and not isinstance(v, str):
                raise BriefError(f"{key} must be a string")
            t = _text(v)
            if kind == "date" and t:
                try:
                    date.fromisoformat(t)
                except ValueError:
                    raise BriefError("exam_date must be an ISO date (YYYY-MM-DD)")
            out[key] = t
    return out


def brief_is_empty(brief) -> bool:
    """Empty means "no brief to compile from", so the course keeps its hand-written tutor_prompt. A syllabus does
    not make a brief non-empty: it is a schedule, not a description of the course, and a course that has only ever
    had a hand-written prompt must keep it when a syllabus is applied. compile_prompt/course_prompt add the
    schedule to whichever prompt results."""
    if not isinstance(brief, dict):
        return True
    return not any((v if isinstance(v, list) else _text(v))
                   for k, v in brief.items() if k != SYLLABUS_KEY)


# ---------------------------------------------------------------- syllabus (Phase 13)

def _line(v) -> str:
    """One topic or reading as a single line. The prompt asks for strings, but the reading shape ALLMS's extractor
    asked for ({author, title, chapters}) is the obvious thing for a model to reach for, so it is flattened here
    rather than thrown away."""
    if isinstance(v, dict):
        bits = [_text(v.get(k)) for k in ("author", "title", "chapters", "pages", "description")]
        v = " — ".join(b for b in bits[:2] if b) + ("".join(f", {b}" for b in bits[2:] if b))
    if not isinstance(v, str):
        return ""
    return " ".join(v.split())[:MAX_LINE].strip()


def _items(v) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        v = re.split(r"[\n;]", v)
    if not isinstance(v, list):
        raise BriefError("topics and readings must be a list")
    out = []
    for x in v:
        line = _line(x)
        if line and line not in out:
            out.append(line)
    return out[:MAX_ITEMS]


_WEEK_NUM = re.compile(r"\d{1,2}")


def _week_number(v) -> str:
    """The teaching week as a bare number. "3", 3, "Week 03" and "week 3-4" all become "3"; anything with no
    usable number is dropped by normalise_syllabus, because a week that cannot be numbered cannot tag a file."""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        n = int(v)
        return str(n) if 1 <= n <= MAX_WEEKS else ""
    m = _WEEK_NUM.search(v) if isinstance(v, str) else None
    if not m:
        return ""
    n = int(m.group(0))
    return str(n) if 1 <= n <= MAX_WEEKS else ""


def normalise_syllabus(raw) -> dict:
    """Validate an extracted or posted syllabus into {"weeks": [{week, title, topics, readings}], "source": str}.

    Weeks are merged and sorted by number, so the same payload always normalises to the same object — that is what
    makes /syllabus/apply idempotent. A week with no usable number is dropped rather than guessed at."""
    if raw is None:
        return {"weeks": [], "source": ""}
    if isinstance(raw, list):
        raw = {"weeks": raw}
    if not isinstance(raw, dict):
        raise BriefError("syllabus must be an object")
    weeks_in = raw.get("weeks")
    if weeks_in is None:
        weeks_in = []
    if not isinstance(weeks_in, list):
        raise BriefError("syllabus.weeks must be a list")
    by_week = {}
    for w in weeks_in:
        if not isinstance(w, dict):
            raise BriefError("each syllabus week must be an object")
        n = _week_number(w["week"] if w.get("week") is not None else w.get("weekNumber"))
        if not n:
            continue
        cur = by_week.setdefault(n, {"week": n, "title": "", "topics": [], "readings": []})
        cur["title"] = cur["title"] or _line(w.get("title"))
        for key in ("topics", "readings"):
            for item in _items(w.get(key)):
                if item not in cur[key]:
                    cur[key].append(item)
            del cur[key][MAX_ITEMS:]
    weeks = [by_week[k] for k in sorted(by_week, key=int)][:MAX_WEEKS]
    return {"weeks": weeks, "source": _line(raw.get("source"))}


def syllabus_block(brief) -> str:
    """The schedule as the tutor sees it. Facts only: what each week covers and what it reads."""
    syl = (brief or {}).get(SYLLABUS_KEY) if isinstance(brief, dict) else None
    weeks = (syl or {}).get("weeks") or []
    if not weeks:
        return ""
    lines = [SYLLABUS_HEADER]
    for w in weeks:
        line = f"Week {w['week']}"
        if w.get("title"):
            line += f" — {w['title']}"
        if w.get("topics"):
            line += ". Topics: " + "; ".join(w["topics"])
        if w.get("readings"):
            line += ". Reading: " + "; ".join(w["readings"])
        lines.append(_sentence(line))
    return "\n".join(lines)


def strip_syllabus(text: str) -> str:
    """Remove a previously compiled schedule from a prompt, so re-applying appends instead of accumulating."""
    t = text or ""
    i = t.find(SYLLABUS_HEADER)
    return (t[:i] if i >= 0 else t).rstrip()


def keep_syllabus(new_brief, old_brief):
    """The course dialog has no syllabus fields, so a brief posted from it carries none. Saving course settings
    must not silently throw away an applied syllabus; only /syllabus/apply changes it."""
    if not isinstance(new_brief, dict) or (new_brief.get(SYLLABUS_KEY) or {}).get("weeks"):
        return new_brief
    keep = (old_brief or {}).get(SYLLABUS_KEY) if isinstance(old_brief, dict) else None
    if isinstance(keep, dict) and keep.get("weeks"):
        return dict(new_brief, **{SYLLABUS_KEY: keep})
    return new_brief


def compile_prompt(brief: dict, name: str = "") -> str:
    """Render the course block of the tutor system prompt. Empty fields render nothing."""
    b = brief or {}
    t = lambda k: _text(b.get(k))
    lines = []

    parts = [p for p in (t("lecturer"), f"WG tutor {t('wg_tutor')}" if t("wg_tutor") else "", t("textbook")) if p]
    name = _text(name)
    if name or parts or t("exam_format"):
        head = "Course specifics" + (f" — {name}" if name else "") + (f" ({'; '.join(parts)})" if parts else "") + "."
        if t("exam_format"):
            head += " Exam: " + _sentence(t("exam_format"))
        lines.append(head)

    meta = [s for s in (f"Course code: {t('course_code')}" if t("course_code") else "",
                        f"Period: {t('period')}" if t("period") else "") if s]
    if meta:
        lines.append(" · ".join(meta) + ".")
    if t("exam_date"):
        lines.append(f"Exam date: {t('exam_date')}.")
    if t("assessment_weighting"):
        lines.append("Assessment weighting: " + _sentence(t("assessment_weighting")))
    if t("permitted_materials"):
        lines.append("Permitted materials in the exam: " + _sentence(t("permitted_materials")))
    if t("method"):
        lines.append(t("method"))
    authority = [x.strip() for x in (b.get("authority_order") or []) if isinstance(x, str) and x.strip()]
    if authority:
        lines.append("AUTHORITY (highest first):\n" + "\n".join(f"{i}. {a}" for i, a in enumerate(authority, 1)))
    tags = [x.strip() for x in (b.get("provenance_tags") or []) if isinstance(x, str) and x.strip()]
    if tags:
        lines.append("Provenance tags for this course: " + " ".join(tags))
    # Free text last: seeded notes refer back to "the authority order above".
    if t("notes"):
        lines.append(t("notes"))
    # The schedule after the prose: it is a reference table, and the notes above never point at it.
    block = syllabus_block(b)
    if block:
        lines.append(block)
    return "\n".join(lines)


def course_prompt(brief, name: str, stored: str) -> str:
    """The prompt a course actually uses: the compiled brief, or the stored prompt when the brief is empty.

    An applied syllabus reaches the tutor either way — appended to the hand-written prompt when there is no brief
    to compile. The old block is stripped first so applying twice does not stack two schedules."""
    if not brief_is_empty(brief):
        return compile_prompt(brief, name)
    return "\n".join(x for x in (strip_syllabus(stored), syllabus_block(brief)) if x)


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48].strip("-")
    return s or "course"


def unique_slug(base: str, taken) -> str:
    taken = set(taken)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _hex6(c: str) -> str:
    c = c.strip().lower()
    return "#" + "".join(ch * 2 for ch in c[1:]) if len(c) == 4 else c


def valid_accent(accent: str) -> str:
    if not isinstance(accent, str) or not re.fullmatch(r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?", accent.strip()):
        raise BriefError("accent must be a hex colour like #5a7384")
    if _hex6(accent) in TAB_COLOURS:
        raise BriefError("that colour belongs to a Blackstone tab — pick another accent")
    return accent.strip()


def pick_accent(used) -> str:
    used = {_hex6(u) for u in used if isinstance(u, str)}
    free = [c for c in PALETTE if c not in used]
    return free[0] if free else PALETTE[len(used) % len(PALETTE)]


def load_seed_brief(seed: str) -> dict:
    return normalise_brief(json.loads((PROMPTS / f"{seed}.json").read_text(encoding="utf-8")))
