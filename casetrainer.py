"""
Case trainer (Phase 20) — the exam-hypothetical issue-spotter.

A "case" is a realistic fact-pattern hypothetical plus N multiple-choice questions on the legal
issues it raises, so the student revises exam-style while doing MCQs. Each MCQ reuses the Phase-11
Question shape — {question, options[4], correct_index, explanation} — and the explanation TEACHES
(why the right option is right, why each wrong one is wrong), citing the material. The fact pattern
is the new wrapper around them.

Like oral.py and essay.py this module holds only what is the same whatever the surface: the two
selectable lengths, the shapes, their validation, and which case to serve next. Two things it
deliberately does NOT own, and each is the point of the phase:

  * The law. Nothing is invented here. The fact pattern and its MCQs are generated in run.py,
    grounded strictly in the course's ticked files, and the writer abstains when the source is thin.
  * Recurrence. A missed MCQ becomes a card and is rated 'Again' through the app's one review path,
    exactly as Phase 11 decided. A second scheduler competing with that one would quietly undo it.
"""

# Both lengths, selectable (settled by Matej 2026-10-12). `mcqs` is the target the writer is asked for;
# `lo`/`hi` are the band the writer may land in — it is told to write FEWER when the material is thin
# rather than pad a case with invented issues, so a short grounded case of three MCQs is fine.
LENGTHS = {
    "short": {"label": "Short hypo", "mcqs": 4, "lo": 3, "hi": 5,
              "facts": "a short hypothetical of about a paragraph (3-6 sentences)"},
    "full":  {"label": "Full exam fact pattern", "mcqs": 8, "lo": 5, "hi": 12,
              "facts": "a full exam-length fact pattern (several paragraphs, multiple parties and events)"},
}
DEFAULT_LENGTH = "short"

OPTIONS = 4              # the Phase-11 Question shape is exactly four options, A-D
FACTS_CHARS = 8000      # a fact pattern, not a dissertation
QUESTION_CHARS = 800
OPTION_CHARS = 400
EXPLANATION_CHARS = 800
CONCEPT_CHARS = 80


def length_of(name) -> str:
    """The requested length, defaulting to 'short'. An unknown value is not an error — it falls to the
    default, the way the rest of the app treats an unexpected choice as the safe one."""
    name = str(name or "").strip().lower()
    return name if name in LENGTHS else DEFAULT_LENGTH


def _clip(text, chars) -> str:
    return str(text or "").strip()[:chars]


def normalise_mcq(q) -> dict | None:
    """Make one generated/stored MCQ safe to act on, or return None if it cannot be trusted.

    A malformed MCQ must never be shown: a missing option would leave fewer than four choices, and a
    `correct_index` out of range would mark every answer wrong. Both are treated as 'drop it', the way
    oral.normalise treats an unrecognised grade as a miss — fail safe, never fail open.
    """
    if not isinstance(q, dict):
        return None
    question = _clip(q.get("question"), QUESTION_CHARS)
    opts = q.get("options")
    if not question or not isinstance(opts, list):
        return None
    options = [_clip(o, OPTION_CHARS) for o in opts if str(o).strip()]
    # Exactly four, and four DISTINCT options: a repeated option is a free elimination and not a real
    # question. Order is preserved so correct_index still points where the writer meant it to.
    if len(options) != OPTIONS or len(set(options)) != OPTIONS:
        return None
    try:
        ci = int(q.get("correct_index"))
    except (TypeError, ValueError):
        return None
    if not 0 <= ci < OPTIONS:
        return None
    return {
        "question": question,
        "options": options,
        "correct_index": ci,
        "explanation": _clip(q.get("explanation"), EXPLANATION_CHARS),
        "concept": _clip(q.get("concept"), CONCEPT_CHARS),
    }


def valid_mcq(q) -> bool:
    return normalise_mcq(q) is not None


def normalise_case(c) -> dict | None:
    """A generated case the UI can trust: a fact pattern and at least one usable MCQ. A case whose MCQs
    are all malformed is dropped rather than shown with an empty question list."""
    if not isinstance(c, dict):
        return None
    facts = _clip(c.get("facts") or c.get("fact_pattern") or c.get("hypothetical"), FACTS_CHARS)
    if not facts:
        return None
    mcqs = [m for m in (normalise_mcq(x) for x in (c.get("mcqs") or c.get("questions") or [])) if m]
    if not mcqs:
        return None
    return {"facts": facts, "thin": bool(c.get("thin")), "mcqs": mcqs}


def valid_case(c) -> bool:
    """A banked (stored) case is usable if it carries a fact pattern and at least one MCQ."""
    return bool(isinstance(c, dict) and str(c.get("facts", "")).strip() and (c.get("mcqs") or []))


def choose(cases):
    """
    The next case to serve: one never seen, else the one seen longest ago.

    A case is a sitting — read the facts, then work several MCQs — not a dozen quick turns, so like
    essay.choose this rotates the bank in order rather than shuffling (that is oral's job). Each case
    carries `seen` (epoch it was last served, absent/None = never) and `created`; ties break by age.
    """
    if not cases:
        return None
    return sorted(cases, key=lambda c: (c.get("seen") or 0.0, c.get("created") or 0.0))[0]


def rating_for(correct: bool) -> int:
    """A graded MCQ becomes one of the app's four ratings for the review path: 2 (Good) when it was
    right, 0 (Again) when it was missed. 'Easy' is never inferred — the same restraint oral.py keeps."""
    return 2 if correct else 0
