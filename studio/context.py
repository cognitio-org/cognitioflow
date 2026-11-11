"""CF Game Studio: the shared context every M4 studio call is built from (model-quality plan, rung 1).

One prompt layout for every role, so the M4 prefix cache is reused and the writer, reviewer, reviser and doctrine
gate all judge by the same aim and terms:

    system:  STUDIO_BRIEF   studio/brief.md (identical for every role)
    user:    COURSE BRIEF   courses.tutor_prompt, else a reviewed studio/briefs/<code>.md
             LEXICON        generated from studio/lexicons/<code>.json, never hand-copied
             SOURCES        ranked passages, keyed S1..Sn (the same block for every role)
             ROLE TASK      last (writer / reviewer / revise / doctrine)

This module only LOADS the studio-owned parts (brief, course brief file, lexicon, exemplars, eval split) and builds
the shared prefix. It never reads course files or calls a model. Stdlib only; nothing here is imported by run.py at
module level or shipped in the prod image.

Exemplars (few-shot games) are fail-closed: an exemplar is used only if its authorship is known and allowed
(Matej-written, or local-model-written and Matej-corrected without closed-model help), its gate card passed, it
comes from a DEV week, and its provenance is clean. Today none qualifies, so the index ships empty.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent
BRIEF_PATH = STUDIO_DIR / "brief.md"
BRIEFS_DIR = STUDIO_DIR / "briefs"
LEXICON_DIR = STUDIO_DIR / "lexicons"
EXEMPLAR_DIR = STUDIO_DIR / "exemplars"
SPLIT_PATH = STUDIO_DIR / "eval" / "split.json"

MAX_EXEMPLARS = 3
EXEMPLAR_AUTHORS = frozenset({"matej", "local-model+matej-corrected"})
DRAFT_MARK = "STATUS: DRAFT"
_CODE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


class ContextError(ValueError):
    """A studio-owned input is missing or malformed. The writer refuses rather than writing without it."""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------------------------------------ the brief

def load_brief(path: Path | None = None) -> tuple[str, str]:
    """(STUDIO_BRIEF text, short hash). Missing or empty -> ContextError (no silent brief-less writing)."""
    p = Path(path) if path else BRIEF_PATH
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ContextError(f"studio brief unreadable: {p.name}: {e}") from e
    if not text:
        raise ContextError(f"studio brief {p.name} is empty")
    return text, sha(text)


def load_course_brief(code: str, stored: str = "", *, briefs_dir: Path | None = None,
                      allow_draft: bool | None = None) -> tuple[str, str]:
    """(course brief text, source label). The course's own tutor_prompt (`stored`) wins. Otherwise a file
    studio/briefs/<code>.md is used, but a file still marked DRAFT is skipped unless allowed
    (CF_STUDIO_ALLOW_DRAFT_BRIEF=1): an unreviewed brief must not steer games silently."""
    stored = (stored or "").strip()
    if stored:
        return stored, "courses.tutor_prompt"
    if not code or not _CODE.fullmatch(code):
        return "", "none"
    p = (Path(briefs_dir) if briefs_dir else BRIEFS_DIR) / f"{code}.md"
    if not p.exists():
        return "", "none"
    text = p.read_text(encoding="utf-8").strip()
    if allow_draft is None:
        allow_draft = os.environ.get("CF_STUDIO_ALLOW_DRAFT_BRIEF", "").strip() == "1"
    if DRAFT_MARK in text and not allow_draft:
        return "", f"skipped (DRAFT): briefs/{code}.md"
    return text, f"briefs/{code}.md" + (" (DRAFT)" if DRAFT_MARK in text else "")


# ------------------------------------------------------------------------------------------------ the lexicon

def lexicon_block(code: str, *, lexicon_dir: Path | None = None) -> tuple[str, str]:
    """(LEXICON block text, lexicon version). Generated from the approved lexicon file, so the writer sees
    exactly the terms the terminology gate enforces. No file -> ("", "none")."""
    if not code or not _CODE.fullmatch(code):
        return "", "none"
    p = (Path(lexicon_dir) if lexicon_dir else LEXICON_DIR) / f"{code}.json"
    if not p.exists():
        return "", "none"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        terms, version = data["terms"], str(data["version"])
        assert isinstance(terms, dict) and terms
    except Exception as e:  # noqa: BLE001 — the gate fails closed on the same file; refuse here too
        raise ContextError(f"lexicon {p.name} malformed: {e}") from e
    lines = [f'- "{term}": never write ' + ", ".join(f'"{s}"' for s in syns) + " instead"
             for term, syns in sorted(terms.items()) if isinstance(syns, list) and syns]
    text = ("LEXICON (the course's protected terms; use the term itself, never these near-synonyms):\n"
            + "\n".join(lines))
    return text, version


# ------------------------------------------------------------------------------------------------ eval split

def load_split(path: Path | None = None) -> dict:
    p = Path(path) if path else SPLIT_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ContextError(f"eval split unreadable: {e}") from e
    if not isinstance(data.get("heldout"), dict) or not isinstance(data.get("dev"), dict):
        raise ContextError("eval split needs 'heldout' and 'dev' objects")
    return data


def split_of(code: str, week, split: dict | None = None) -> str:
    """'heldout' | 'dev' | 'unassigned' for a course code and week. A scope of several weeks that touches a
    held-out week is held-out (fail closed: held-out weeks must never leak into tuning or training)."""
    s = split if split is not None else load_split()
    weeks = [w.strip() for w in str(week or "").split(",") if w.strip()]
    held = {str(w) for w in s["heldout"].get(code, [])}
    dev = {str(w) for w in s["dev"].get(code, [])}
    if not weeks or any(w.lower() == "all" for w in weeks):
        return "heldout" if held else "unassigned"
    if any(w in held for w in weeks):
        return "heldout"
    if all(w in dev for w in weeks):
        return "dev"
    return "unassigned"


# ------------------------------------------------------------------------------------------------ exemplars

def exemplar_problems(ex: dict, split: dict | None = None) -> list:
    """Why an exemplar may NOT be used; empty list = usable. Fail closed on anything unknown."""
    bad = []
    if not isinstance(ex, dict):
        return ["not an object"]
    if ex.get("author") not in EXEMPLAR_AUTHORS:
        bad.append(f"authorship {ex.get('author')!r} is not known/allowed")
    if ex.get("edit_assisted") is not False:
        bad.append("edit_assisted must be literally false (edits made with closed-model help taint the game)")
    if ex.get("provenance") != "clean":
        bad.append("provenance is not 'clean'")
    card = ex.get("card")
    if not (isinstance(card, dict) and card.get("overall_pass") is True):
        bad.append("its gate card did not pass")
    try:
        sp = split_of(str(ex.get("course") or ""), ex.get("week"), split)
    except ContextError as e:
        sp = f"unknown ({e})"
    if sp != "dev":
        bad.append(f"week split is {sp!r}, not 'dev'")
    if not isinstance(ex.get("game"), dict) or not ex.get("mix"):
        bad.append("needs 'game' (writer shape) and 'mix'")
    return bad


def load_exemplars(code: str, *, exemplar_dir: Path | None = None, split: dict | None = None,
                   limit: int = MAX_EXEMPLARS) -> tuple[list, list]:
    """(usable exemplars, rejected [(id, reasons)]) for a course, at most `limit`, one per round mix first.
    Reads exemplars/index.json: [{"id", "file", "course"}]; each file holds the exemplar record."""
    d = Path(exemplar_dir) if exemplar_dir else EXEMPLAR_DIR
    idx = d / "index.json"
    if not idx.exists():
        return [], []
    entries = json.loads(idx.read_text(encoding="utf-8"))
    ok, rejected = [], []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict) or e.get("course") != code:
            continue
        try:
            ex = json.loads((d / str(e.get("file") or "")).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            rejected.append((e.get("id"), [f"unreadable: {err}"]))
            continue
        why = exemplar_problems(ex, split)
        (rejected.append((e.get("id"), why)) if why else ok.append({**ex, "id": e.get("id")}))
    seen, first, rest = set(), [], []
    for ex in ok:                                       # one per mix first, then the rest
        (rest if ex["mix"] in seen else first).append(ex)
        seen.add(ex["mix"])
    return (first + rest)[:max(0, int(limit))], rejected


def exemplar_block(exemplars: list) -> str:
    if not exemplars:
        return ""
    parts = [f"EXAMPLE GAME {i} (mix {ex['mix']}; a reviewed game from another week; copy its quality, "
             f"not its facts):\n{json.dumps(ex['game'], ensure_ascii=False)}" for i, ex in enumerate(exemplars, 1)]
    return "\n\n".join(parts)


# ------------------------------------------------------------------------------------------------ the whole context

def load(course: dict, code: str, *, allow_draft: bool | None = None) -> dict:
    """Everything studio-owned a writer call needs, with hashes for the provenance record."""
    brief, brief_hash = load_brief()
    course_brief, cb_source = load_course_brief(code, (course or {}).get("tutor_prompt") or "",
                                                allow_draft=allow_draft)
    lex, lex_version = lexicon_block(code)
    exemplars, rejected = load_exemplars(code)
    return {"brief": brief, "brief_hash": brief_hash, "course_brief": course_brief,
            "course_brief_source": cb_source, "course_brief_hash": sha(course_brief) if course_brief else "",
            "lexicon": lex, "lexicon_version": lex_version, "exemplars": exemplars,
            "exemplar_ids": [e["id"] for e in exemplars], "exemplars_rejected": rejected,
            "exemplar_block": exemplar_block(exemplars), "code": code}


def shared_prefix(ctx: dict, sources: str) -> str:
    """The user-message prefix every role shares, in plan order: COURSE BRIEF, LEXICON, SOURCES."""
    parts = []
    if ctx.get("course_brief"):
        parts.append("COURSE BRIEF (how this course is taught and examined):\n" + ctx["course_brief"])
    if ctx.get("lexicon"):
        parts.append(ctx["lexicon"])
    parts.append(sources)
    return "\n\n".join(parts)


def user_message(ctx: dict, sources: str, task: str) -> str:
    """Shared prefix, then the role task LAST."""
    return shared_prefix(ctx, sources) + "\n\n" + task
