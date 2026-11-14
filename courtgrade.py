"""courtgrade.py — grade a moot-court free-text answer LOCALLY, with no model call.

The courtroom (`/api/courses/{cid}/court/reply`) used to send every student answer to the
MAIN cloud tier to be graded. That is the one play-time call this app cannot cache (a free-text
answer is different every time), so it was the hardest external-AI dependency to remove — and the
most damaging to keep: a lecture-hall with no network, or a spent AI budget, left the courtroom
unable to grade at all.

This module grades the answer where the student is sitting, from material already on the box:

  * the student's OWN notes about the case (the same `_case_context` run.py already builds), and
  * `relevance.rank` — the pure-stdlib TF-IDF cosine the app ships (the audit named it the swap-in
    seam), with the local CPU embedding model (`embed.py`) folded in when it is loaded.

No frontier/cloud/gateway call ever runs here. `grade()` returns the exact dict shape
`oral.normalise` produces (mastery / verdict / spoken / note / rating), so run.py's reply handler
and `_remember_miss` are untouched below the seam.

How it grades (all local, all deterministic given the same notes):
  1. Reference = the few note sentences that best match the BENCH QUESTION (what a good answer
     should land on), by TF-IDF rank over the full context so the IDF is meaningful.
  2. Rubric = the salient terms in those reference sentences MINUS the terms already in the
     question (so restating the question earns nothing); case names, article refs and numbers
     weigh double.
  3. Score = blend of (a) similarity of the answer to the reference — embedding cosine when the
     local model is loaded, else lexical TF-IDF — and (b) how much of the rubric the answer covers.
  4. Gates catch the ways a lexical grader is gamed or misled: too-short answers, keyword-stuffed
     lists with no connective tissue, and verbatim note dumps are capped; a reference the ranker
     could not find at all yields a neutral "shaky" rather than a confident wrong "missed".

The thresholds are calibrated against synthetic anchors built from the notes themselves (see
`scripts/prefill_game_caches.py --calibrate`), not against labelled data the app does not have;
they are intentionally conservative and are the single most likely thing to need tuning on real
answers. Known local-grader blind spot: a flatly negated answer ("the court found *no* breach")
shares the vocabulary of the correct one, so lexical and small-embedding scorers can over-credit
it — the honest escalation for that nuance is the LOCAL M4, never a frontier call.
"""
from __future__ import annotations

import math
import re

import embed
import relevance

# --- tokenisation -------------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]{3,}")
_SENT = re.compile(r"(?<=[.!?;])\s+|\n+")
_TAG = re.compile(r"\[[A-Za-z][^\]]*\]")        # provenance tags: [WG] [LECTURE] [SCHUTZE p.] [ADDED]
_CITE = re.compile(r"\b[Aa]rt(?:icle)?\.?\s*(\d+)")   # "Art. 34" / "Article 34(1)" → one "art34" token
_NUMish = re.compile(r"^(art)?\d")

# Everyday words plus a few that recur in these notes; a rubric built of these would be free to hit.
_STOP = frozenset(
    "the a an and or but of to in on at by for with from into as is are was were be been being "
    "this that these those it its they them their there here which who whom whose what when where "
    "why how not no nor so than then thus also such can could would should may might must will "
    "shall do does did done has have had having one two three more most less least very any all "
    "each both few other some own same about above below under over between within without must "
    "case court held holding rule measure student notes answer question".split()
)


def _clean(text: str) -> str:
    """Drop provenance tags, markdown emphasis and the `[title] …` framing `_case_context` adds."""
    text = _TAG.sub(" ", text or "")
    text = text.replace("…", " ").replace("*", " ").replace("_", " ").replace("`", " ")
    return re.sub(r"\s+", " ", text).strip()


def _normalise(text: str) -> str:
    return _CITE.sub(lambda m: f"art{m.group(1)}", text or "")


def _tokens(text: str) -> list:
    return _WORD.findall(_normalise(_clean(text)).lower())


def _content(text: str) -> list:
    return [t for t in _tokens(text) if t not in _STOP]


def sentences(context: str) -> list:
    """The context split into gradable sentences, tags and framing stripped, trivia dropped."""
    out = []
    for raw in _SENT.split(context or ""):
        s = _clean(raw)
        if 15 <= len(s) <= 400:
            out.append(s)
    return out


# --- scoring ------------------------------------------------------------------------------------
REF_K = 3                 # how many note sentences stand in for "a good answer"
REF_FLOOR = 0.02          # below this the ranker found nothing worth calling a reference
MIN_CONTENT = 4           # fewer content words than this is never more than a guess
W_SIM_EMBED = 0.6         # embeddings capture legal synonymy; lean on them when they are loaded
W_SIM_LEX = 0.4           # lexical cosine is noisier; let the rubric carry more of the weight
# Calibrated on synthetic anchors built from the notes (no labelled data): a near-verbatim/strong
# answer clears SOLID, off-topic and empty answers fall below SHAKY, and the broad middle —
# partial or correct-but-paraphrased answers the lexical scorer cannot tell from a plausible wrong
# one — lands in SHAKY, the safe outcome (a review card + "the bench is not satisfied, press on",
# never a false "solid"). The embedding path lifts genuine paraphrases out of that middle. These
# two numbers are the single most likely thing to need tuning on real answers.
SOLID, SHAKY = 0.55, 0.15
SEMANTIC_OVERRIDE = 0.82  # a very close dense match is solid even if the rubric wording differs


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _embed_sim(answer: str, refs: list):
    """Best dense-embedding cosine of the answer against any reference sentence, or None if the
    local model is not loaded here (then the lexical scorer carries the whole similarity term)."""
    if not refs:
        return None
    try:
        if not embed.ready():
            return None
        vecs = embed.embed([answer] + refs)
    except Exception:
        return None
    if len(vecs) != len(refs) + 1:
        return None
    return max((_cosine(vecs[0], v) for v in vecs[1:]), default=0.0)


def _rubric(refs: list, question: str) -> dict:
    """Salient reference terms the question did not already hand the student, weighted: a case name
    or an article/number pulls double, because missing those is what a bench actually presses on."""
    q = set(_content(question))
    weights: dict = {}
    for ref in refs:
        caps = {w.lower() for w in re.findall(r"\b[A-Z][A-Za-z]{2,}", _clean(ref))}  # proper nouns before lowering
        for t in _content(ref):
            if t in q:
                continue
            weights[t] = max(weights.get(t, 1.0), 2.0 if (t in caps or _NUMish.match(t)) else 1.0)
    return weights


def _keyword_cover(answer_tokens: set, rubric: dict) -> float:
    if not rubric:
        return 0.0
    hit = sum(w for t, w in rubric.items() if t in answer_tokens)
    return hit / sum(rubric.values())


def _function_ratio(answer: str) -> float:
    toks = _tokens(answer)
    if not toks:
        return 0.0
    return sum(1 for t in toks if t in _STOP) / len(toks)


def _verbatim_dump(answer: str, context: str) -> bool:
    """A long paste of the notes themselves, not an argument: most of the answer's 4-word runs are
    already in the context, and the answer is far longer than a single reference sentence."""
    atoks, ctoks = _tokens(answer), _tokens(context)
    if len(atoks) < 30:
        return False
    cgrams = {tuple(ctoks[i:i + 4]) for i in range(len(ctoks) - 3)}
    agrams = [tuple(atoks[i:i + 4]) for i in range(len(atoks) - 3)]
    if not agrams:
        return False
    contained = sum(1 for g in agrams if g in cgrams) / len(agrams)
    return contained >= 0.6


_SPOKEN = {
    "solid": "That holds up — you reached the test and applied it. The bench is satisfied.",
    "shaky": "Part of that was sound, but the bench is not satisfied yet — press the point you left open and answer again.",
    "missed": "That did not reach it. Look again at what your notes say on this case, then answer the bench once more.",
}
_VERDICT = {"solid": "Solid", "shaky": "Partly there", "missed": "Not yet"}


def grade(question: str, answer: str, context: str) -> dict:
    """Grade one answer locally. Returns {mastery, verdict, spoken, note, rating}. Never raises for a
    bad answer and never calls a model: an empty or garbled answer simply grades 'missed'."""
    import oral  # local import avoids a cycle; oral.normalise owns the final shape and rating

    answer = (answer or "").strip()
    sents = sentences(context)
    acontent = _content(answer)

    def _out(mastery, note=""):
        return oral.normalise({"mastery": mastery, "verdict": _VERDICT[mastery],
                               "spoken": _SPOKEN[mastery], "note": note})

    # The GAP the bench pressed, grounded in the student's own notes, becomes the card back on a
    # miss: the note sentence that best matches the QUESTION — what the student should have said.
    q_scores = relevance.rank(question, sents) if sents else []
    q_best = max(range(len(sents)), key=lambda i: q_scores[i], default=-1)
    note = (sents[q_best] if q_best >= 0 and q_scores[q_best] >= REF_FLOOR
            else (sents[0] if sents else ""))[:240]

    if len(acontent) < MIN_CONTENT:
        return _out("missed", note)
    if not sents:
        # The notes discuss the case (court build required it) but not this exact bench point:
        # grade neutrally and leave no misleading card rather than assert a confident "missed".
        return _out("shaky", "")

    # ANSWER-ANCHORED: find the note sentence(s) the student is clearly talking about, then judge
    # whether they got them right — ranking the reference by the QUESTION instead retrieves the
    # sentence that merely echoes the question's wording, not the one that answers it.
    a_scores = relevance.rank(answer, sents)
    ranked = sorted(range(len(sents)), key=lambda i: a_scores[i], reverse=True)
    ref_idx = [i for i in ranked[:REF_K] if a_scores[i] >= REF_FLOOR] or ranked[:1]
    refs = [sents[i] for i in ref_idx]

    # Similarity: dense when the local embedder is loaded, else lexical TF-IDF over the context.
    emb = _embed_sim(answer, refs)
    if emb is not None:
        sim, w_sim = emb, W_SIM_EMBED
    else:
        sim, w_sim = (max((a_scores[i] for i in ref_idx), default=0.0), W_SIM_LEX)

    # Rubric from the single best-matching sentence (not the union of the case's every sentence,
    # which would demand a student answer one bench question with the whole case).
    kw = _keyword_cover(set(acontent), _rubric(refs[:1], question))

    # Gaming guards (Gemini pass): a keyword-stuffed list with no connective words, or a verbatim
    # note dump, cannot buy its way to "solid".
    stuffing = _function_ratio(answer) < 0.10 and len(acontent) >= 6
    capped = stuffing or _verbatim_dump(answer, context)

    score = w_sim * sim + (1.0 - w_sim) * kw
    if emb is not None and emb >= SEMANTIC_OVERRIDE and not capped:
        mastery = "solid"
    elif score >= SOLID and not capped:
        mastery = "solid"
    elif score >= SHAKY:
        mastery = "shaky"
    else:
        mastery = "missed"

    return _out(mastery, "" if mastery == "solid" else note)
