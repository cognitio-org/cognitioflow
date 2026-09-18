"""
Essay practice (Phase 17) — the part that is the same whatever the surface.

Cards already cover recall. This covers the thing the exam actually tests: producing the answer.
Three decisions shape everything here, and each is deliberate.

  * The student writes FIRST. The model answer is not part of the question — it is unreachable until
    an answer has been submitted, because reading a good structure before writing one teaches
    recognition, not production. `unlocked()` is the only gate, and it is a gate, not a preference.
  * A grade is feedback, not a number. The method the course examines on has three moves; the grade
    is a comment on each. There is no total, no percentage, nothing to optimise or compare.
  * The exam method is NOT restated here. `LIMBS` names the moves that run.py's own `MODES["apply"]`
    block already sets out, and the grader is handed that block verbatim. If this module ever grows
    its own wording of the method it becomes a second copy that drifts from the tutor's.

It sits beside `oral.py` rather than inside it because the two produce different things: oral grades
a spoken answer into one mastery word that feeds the app's review queue, and essay grades a written
one into a comment per move that feeds nothing. What they do share — the grading vocabulary — is
imported from there rather than written again.
"""
import oral

# The three moves of the method, in order. The keys are the JSON the grader returns; the labels are
# what the page shows. Read them against run.py's MODES["apply"] — they name its moves and nothing more.
LIMBS = (
    ("applicability", "Applicability"),
    ("restriction", "Restriction or scope"),
    ("justification", "Justification and proportionality"),
)

STANDING = oral.MASTERY          # solid / shaky / missed — the app already has this vocabulary
COMMENT_WORDS = 60               # per move. Long enough to name the article and the fix, short enough to read.
OUTSIDE = 6                      # how many [OUTSIDE FILES] authorities are worth listing back
ANSWER_CHARS = 20000             # an exam answer, not a dissertation
QUESTION_CHARS = 2000


def _clip(text, words):
    return " ".join(str(text or "").split()[:words])


def answered(text) -> bool:
    """Whitespace is not an answer. Checked before any model call — an empty page costs nothing to mark."""
    return bool(str(text or "").strip())


def valid_question(q) -> bool:
    """A banked question is only usable if it carries the model answer that is shown after submission."""
    return bool(isinstance(q, dict) and str(q.get("question", "")).strip() and str(q.get("model", "")).strip())


def unlocked(attempt) -> bool:
    """
    Whether the model answer may be shown. The one rule: an answer has been submitted for marking.

    Submission, not a successful grade — a grader outage must not lock away work the student has
    already done, and it cannot be used to peek either, because the answer is saved at the same moment.
    """
    return bool(attempt and attempt.get("submitted") and answered(attempt.get("answer")))


def choose(questions, last_attempt):
    """
    The next question: one never attempted, else the one attempted longest ago.

    Deliberately not random. `oral.choose` shuffles because a viva is dozens of quick turns and
    repetition is the risk; an essay is one long sitting, so working the bank in order is worth more
    than surprise. `last_attempt` maps question id -> epoch of the last attempt (absent = never).
    """
    if not questions:
        return None
    return sorted(questions, key=lambda q: (last_attempt.get(q.get("id"), 0.0), q.get("created") or 0.0))[0]


def blank_grade() -> dict:
    """The shape of a grade before anything has been marked — the page renders from one shape only."""
    return {"limbs": [{"limb": k, "label": l, "standing": "", "comment": ""} for k, l in LIMBS], "outside": []}


def normalise_grade(graded) -> dict:
    """
    Make a marker's JSON safe to show. Every move of the method appears exactly once and in order,
    whatever the model returned: a missing move is the one thing the student most needs to see, so it
    is reported as missed rather than quietly dropped from the list.
    """
    got = graded if isinstance(graded, dict) else {}
    raw = got.get("limbs")
    raw = raw if isinstance(raw, dict) else {}
    limbs = []
    for key, label in LIMBS:
        item = raw.get(key)
        item = item if isinstance(item, dict) else {}
        standing = str(item.get("standing", "")).strip().lower()
        if standing not in STANDING:
            standing = "missed"
        limbs.append({"limb": key, "label": label, "standing": standing,
                      "comment": _clip(item.get("comment"), COMMENT_WORDS)})
    listed = got.get("outside")
    outside = [str(x).strip()[:120] for x in listed if str(x).strip()][:OUTSIDE] if isinstance(listed, list) else []
    return {"limbs": limbs, "outside": outside}
