"""
Oral revision engine (Phase 11c) — the part that is the same whatever the voice or the framework.

The tutor asks a question aloud, the student answers aloud, a model grades the substance and returns
solid / shaky / missed. Two things then happen, and keeping them separate matters:

  * WITHIN a session, `choose()` decides what to ask next — misses jump the queue, and a question just
    asked goes on a short cooldown so it is not repeated back to back.
  * ACROSS sessions, nothing here decides anything. A grade maps to one of the app's four ratings and
    goes through schedule.next_review(), so FSRS owns when a card truly comes back. A second scheduler
    competing with that one would quietly undo it.
"""

MASTERY = ("solid", "shaky", "missed")

# How hard a concept pulls to the front of this session's queue.
WEIGHT = {"missed": 100, "shaky": 40, "untested": 20, "solid": 4}

# Turns before the same question may be asked again in this session.
COOLDOWN = {"missed": 1, "shaky": 2, "solid": 6}

# The app's ratings: 0 Again, 1 Hard, 2 Good, 3 Easy. "Easy" is never inferred from speech.
RATING = {"missed": 0, "shaky": 1, "solid": 2}

TEACH_AFTER = 2          # miss the same concept twice and explain it before testing it again
SPOKEN_WORDS = 45        # the prompt's budget; also what keeps replies fast and cheap
NOTE_WORDS = 25


def rating_for(mastery: str) -> int:
    """A spoken grade becomes one of the app's four ratings. Unknown grades are treated as a miss."""
    return RATING.get(mastery, 0)


def weight_of(question: dict, mastery: dict) -> int:
    return WEIGHT.get(mastery.get(question.get("concept"), "untested"), WEIGHT["untested"])


def tick(cooldown: dict) -> dict:
    """One turn passes."""
    return {k: v - 1 for k, v in cooldown.items() if v - 1 > 0}


def choose(questions, mastery, cooldown, roll=0.0):
    """
    Pick the next question. `roll` is a number in [0,1) — the caller supplies randomness so this stays
    testable. Questions on cooldown are skipped unless every one of them is, in which case the
    cooldown is ignored rather than leaving the student with nothing to answer.
    """
    if not questions:
        return None
    live = [q for q in questions if q.get("id") not in cooldown] or list(questions)
    total = sum(weight_of(q, mastery) for q in live)
    if total <= 0:
        return live[0]
    target = roll * total
    for q in live:
        target -= weight_of(q, mastery)
        if target < 0:
            return q
    return live[-1]


def should_teach(concept: str, misses: dict) -> bool:
    """Two misses on the same concept means testing it again is pointless until it has been explained."""
    return misses.get(concept, 0) >= TEACH_AFTER


def _clip(text, words):
    parts = str(text or "").split()
    return " ".join(parts[:words])


def normalise(graded: dict) -> dict:
    """
    Make a model's JSON safe to act on. A grader that returns something unexpected must not be able to
    mark a wrong answer as solid, so anything unrecognised falls to 'missed'.
    """
    got = graded if isinstance(graded, dict) else {}
    mastery = str(got.get("mastery", "")).strip().lower()
    if mastery not in MASTERY:
        mastery = "missed"
    note = "" if mastery == "solid" else _clip(got.get("note"), NOTE_WORDS)
    return {
        "mastery": mastery,
        "verdict": _clip(got.get("verdict"), 6) or {"solid": "Solid", "shaky": "Partly there", "missed": "Not yet"}[mastery],
        "spoken": _clip(got.get("spoken"), SPOKEN_WORDS),
        "note": note,
        "rating": rating_for(mastery),
    }


def valid_question(q: dict) -> bool:
    """A question is only usable if it carries the answer to grade against and the concept to track."""
    return bool(isinstance(q, dict) and str(q.get("question", "")).strip()
                and str(q.get("model", "")).strip() and str(q.get("concept", "")).strip())
