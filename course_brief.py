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
    known = {k for k, _, _ in BRIEF_FIELDS}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise BriefError(f"unknown brief field(s): {', '.join(unknown)}")
    out = {}
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
    if not isinstance(brief, dict):
        return True
    return not any((v if isinstance(v, list) else _text(v)) for v in brief.values())


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
    return "\n".join(lines)


def course_prompt(brief, name: str, stored: str) -> str:
    """The prompt a course actually uses: the compiled brief, or the stored prompt when the brief is empty."""
    return (stored or "") if brief_is_empty(brief) else compile_prompt(brief, name)


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
