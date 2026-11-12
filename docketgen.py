"""Case Docket games written from his own files (asked for 2026-09-29).

When new material lands for a week, a small team writes that week's 3D courtroom game:

  * the WRITER turns the week's files into a game in the player's own JSON (the same shape
    games/to_json.py produces for the hand-made IIEL games), citing the files by key;
  * the CHECKS here hold it to the player's contract - phases in order, one right answer in four,
    known sets, every citation pointing at a real file - and to the course: a case, article or
    ECLI named anywhere in the game must be found in the files (citecheck does the finding);
  * the REVIEWER, a second model, reads the questions against the sources and says what is wrong.

A game is only a draft until he approves it. Nothing here touches the database or a model; run.py
does both, so this module stays pure and testable.
"""
import json
import re
import unicodedata

SET_KINDS = ("customs_yard", "office", "courtroom", "street", "classroom", "parliament", "generic", "tv_studio")
ARRIVAL_SETS = ("street", "customs_yard")
PHASES = ("arrival", "examination", "verdict", "epilogue")
KEYS = "ABCD"
# Interaction kinds a quiz may declare. "mcq" (the default when no `kind` is set) is the frozen A–D
# path. The produce-type kinds carry a cached `answer` and NO `options`, are graded deterministically
# in the browser (play/player/grade.js), and classify as "generation" in the studio retrieval gate.
PRODUCE_KINDS = ("spot", "order", "slot")
INTERACTION_KINDS = ("mcq",) + PRODUCE_KINDS
MIN_ROUNDS, MAX_ROUNDS = 2, 4
SOURCE_CHARS = 110_000            # what the writer reads from a week; past exams and WG material first
FILE_CHARS = 40_000               # no single reader may crowd the rest out
AUTO_STALE_S = 20 * 60            # a writing job not heard from in this long has died with its instance
# Error prefixes the studio gates write on a failed row (S5/S9). `weeks_needing_games` counts them per
# material version when the caller passes `max_failures` / `max_infra_failures`; otherwise they are ignored.
GATE_BLOCKED = "Blocked by the quality gates"
GATE_UNAVAILABLE = "Gates unavailable"
SLOT_STATUSES = ("writing", "draft", "approved", "discarded")   # rows that used one of the week's draft slots
SLOT_WINDOW_S = 7 * 86400

WRITER = """You write one short 3D courtroom game for a law student, from his own course files only.

The fantasy: he is the lawyer. He arrives on a wet city street at dusk, walks into the building, the case is put
to him, the judge or opposing counsel examines him round by round, and he wins or loses on the law.
Everything is original fiction (invented people, firms and fictional states are fine; follow the course's own
naming style for hypotheticals if the files have one). No real brands, no film or game characters.

The law must come from the files and nothing else. Every rule, case, article and test you use must be stated in
the supplied files. Cite the file key for every legal claim in teaching text and in the IRAC, as [KEY] or
[KEY p.N] when the text shows a page number. Never cite a key that is not in SOURCES. If the files do not
support a point, leave the point out.

Shape (return ONLY this JSON, no prose, no code fence):
{
 "title": "The <Short Evocative Case Name>",
 "logline": "2-3 sentences: who the client is, what went wrong, what the lawyer must show tonight",
 "learning_goal": "By the end, the player can: 1. ... 2. ... 3. ...",
 "case_file": ["Claimant: ...", "The measure: ...", "Key fact: ..."],
 "scenes": [
  {"id": "s1", "title": "Arrival + Briefing", "phase": "arrival", "set": "street",
   "slug": {"int_ext": "EXT", "place": "...", "time": "DUSK, WET"},
   "action": ["one or two sentences of what the player sees and does"],
   "dialogue": [{"speaker": "NAME", "line": "...", "cites": []}]},
  {"id": "s2", "title": "Examination - <topic>", "phase": "examination", "set": "courtroom",
   "action": ["..."], "dialogue": [{"speaker": "JUDGE <NAME>", "line": "...", "cites": []}],
   "quiz": {"id": "q1", "question": "an exam-shaped question on these facts",
    "options": [
     {"key": "A", "text": "an answer as a student would argue it", "correct": true, "stamp": "SUSTAINED",
      "outcome_title": "", "story": "", "teaching": "why this scores, with [KEY] citations", "cites": ["KEY"]},
     {"key": "B", "text": "a tempting wrong answer: the classic mistake", "correct": false, "stamp": "OVERRULED",
      "outcome_title": "Short name of the mistake.", "story": "one sentence of what happens in court",
      "teaching": "why it fails, with [KEY] citations", "cites": ["KEY"]}
    ]}},
  {"id": "s4", "title": "Verdict", "phase": "verdict", "set": "courtroom", "action": ["..."],
   "dialogue": [{"speaker": "JUDGE <NAME>", "line": "...", "cites": []}]},
  {"id": "s5", "title": "Epilogue", "phase": "epilogue", "set": "generic", "action": ["..."], "dialogue": []}
 ],
 "verdict": {"outcome": "WON", "irac": [{"issue": "...", "rule": "... [KEY]", "application": "...", "conclusion": "..."}],
             "takeaway": "one line to remember for the exam"},
 "checks": [{"n": 1, "claim": "a legal claim the game relies on", "cites": ["KEY"]}]
}

Rules for the shape:
- Scenes in this order: exactly one arrival, then 2 to 3 examination scenes (one quiz each), one verdict, one epilogue.
- The arrival set is "street" or "customs_yard"; examination and verdict use "courtroom" (or "office", "parliament",
  "classroom" if the case truly happens there); the epilogue uses "generic".
- Every quiz has exactly four options, A to D, exactly one correct, the right one not always A. Wrong options are the
  mistakes students really make with this material (the files' "typical errors", traps, WG corrections).
- Questions are exam-shaped: apply the rule to these facts, in the order the course teaches the test.
- Dialogue is short and spoken: 3 to 8 lines a scene, speakers in CAPITALS, the same names throughout.
- 1 to 3 checks per examination round."""

REVIEWER = """You check a law quiz game against the student's own course files before he sees it.
For each examination round, and for the verdict, check: is the option marked correct actually right according to the
SOURCES? Is any wrong option in fact also right, or right in part? Does any teaching text state law the SOURCES do not
support, or cite a key for something that key does not say? Is anything off-syllabus for this week?
Return ONLY JSON: {"verdict": "ok" | "fix", "issues": [{"where": "q1 option B", "problem": "...", "severity": "high" | "low"}]}
"high" is anything that would teach him wrong law or mark a right answer wrong. Say "ok" with no issues when it is sound."""

REVISE = """The reviewer found problems with the game below. Return the whole game again, as the same JSON, with every
"high" issue fixed and nothing else changed. Use only the SOURCES; drop a point rather than invent support for it."""


# ---------------------------------------------------------------- sources

def source_keys(files: list) -> dict:
    """{KEY: file} for the files a game is written from: S1, S2, ... in the order they are given."""
    return {f"S{i}": f for i, f in enumerate(files, 1)}


def sources_block(keyed: dict) -> str:
    """The SOURCES the writer and reviewer read, each file's text capped so one reader cannot crowd out the rest."""
    parts, budget = [], SOURCE_CHARS
    for key, f in keyed.items():
        if budget <= 0:
            break
        text = (f.get("text") or "")[:min(FILE_CHARS, budget)]
        budget -= len(text)
        parts.append(f'<source key="{key}" file="{f.get("name", "")}" kind="{f.get("role") or f.get("kind") or ""}">\n{text}\n</source>')
    return "SOURCES:\n" + "\n\n".join(parts)


def sources_json(keyed: dict) -> dict:
    """The game's own "sources" legend, the shape the player's Claims & sources drawer reads."""
    return {k: {"file": f.get("name", ""), "kind": f.get("role") or f.get("kind") or "", "note": f.get("label") or ""} for k, f in keyed.items()}


# ---------------------------------------------------------------- the checks

# [S1], [S1 p.4], and (WRITER v2.1+) a leaked sentence id [S1.18] / [S1.18-S1.20]: group 1 is always the source key.
_CITE = re.compile(r"\[([A-Z][A-Z0-9]{0,5})(?:\.[0-9]+(?:\s*[-\u2013\u2014]\s*(?:[A-Z][A-Z0-9]{0,5}\.)?[0-9]+)?)?"
                   r"(?:\s+p{1,2}\.\s*[0-9]+(?:\s*[-–]\s*[0-9]+)?)?\]")


def _cite_key(c) -> str:
    """The source key a cite names: "S1", "[S1]", "S1 p.4" -> "S1". A sentence id or range ("S1.18", "[S1.18]",
    "S1.18-S1.20", "S1.18-20") is a citation of its source, so it is "S1" too (the writer v2 pilot put sentence ids
    in "cites" lists). A malformed or cross-source ref ("S1.x", "S1.4-S2.5") is returned as typed, so the
    citation check still reports it as an unknown source."""
    s = str(c).strip().strip("[]").strip()
    if not s:
        return ""
    ref = _parse_sentence_ref(s) if "." in s.split()[0] else None
    if ref and ref[0]:
        return ref[0]
    return s if "." in s.split()[0] else s.split()[0]


def all_text(game: dict) -> str:
    """Every word a player could read, for the citation check."""
    out = [game.get("title", ""), game.get("logline", ""), game.get("learning_goal", "")] + list(game.get("case_file") or [])
    for s in game.get("scenes") or []:
        out += list(s.get("action") or []) + [d.get("line", "") for d in s.get("dialogue") or []]
        q = s.get("quiz") or {}
        out.append(q.get("question", ""))
        for o in q.get("options") or []:
            out += [o.get("text", ""), o.get("story", ""), o.get("teaching", "")]
        # produce-type quizzes carry their player-visible text outside `options`, so the citation
        # check sees the cites in a fact pattern, teaching note or answer label too.
        out += [q.get("text", ""), q.get("teaching", "")]
        ans = q.get("answer") or {}
        for it in ans.get("issues") or []:
            out.append(it.get("label", ""))
        for coll in ("bank", "elements", "facts", "taxonomy"):
            for x in ans.get(coll) or []:
                out.append(x.get("label", ""))
    v = game.get("verdict") or {}
    for r in v.get("irac") or []:
        out += [r.get(k, "") for k in ("issue", "rule", "application", "conclusion")]
    out.append(v.get("takeaway", ""))
    return "\n".join(str(x) for x in out if x)


def _spans_ok(spans) -> bool:
    """A list of [start, end] integer character offsets, start < end, 0 <= start."""
    if not isinstance(spans, list) or not spans:
        return False
    for sp in spans:
        if not (isinstance(sp, (list, tuple)) and len(sp) == 2):
            return False
        a, b = sp
        if not (isinstance(a, int) and isinstance(b, int) and 0 <= a < b):
            return False
    return True


def _norm_text(text) -> str:
    """The same normalisation the player applies before computing offsets: CR-stripped, NFC."""
    return unicodedata.normalize("NFC", str(text or "").replace("\r\n", "\n").replace("\r", "\n"))


def _validate_produce_answer(qid, kind, q) -> list:
    """Per-kind checks on a produce-type quiz's cached answer key. Empty list when it is gradable."""
    bad = []
    ans = q.get("answer")
    if not isinstance(ans, dict) or not ans:
        return [f"{qid} ({kind}) has no answer key."]
    if kind == "spot":
        norm = _norm_text(q.get("text"))
        if not norm.strip():
            bad.append(f"{qid} (spot) has no fact text for the player to select.")
        if any(ord(c) > 0xFFFF for c in norm):
            # Python offsets count code points; JS .length/.slice count UTF-16 units, so an astral
            # char (emoji, rare CJK) would shift every baked offset against the browser's.
            bad.append(f"{qid} (spot) fact text contains astral characters, which misalign JS offsets.")
        issues = ans.get("issues")
        if not isinstance(issues, list) or not issues:
            bad.append(f"{qid} (spot) needs at least one issue in its answer.")
            issues = []
        taxo_ids = {str(t.get("id")) for t in (ans.get("taxonomy") or []) if isinstance(t, dict) and t.get("id")}
        for it in issues:
            iid = str((it or {}).get("id") or "")
            if not iid:
                bad.append(f"{qid} (spot) has an issue with no id.")
            elif taxo_ids and iid not in taxo_ids:
                bad.append(f"{qid} (spot) issue {iid!r} is not in the taxonomy.")
            spans = (it or {}).get("spans")
            if not _spans_ok(spans):
                bad.append(f"{qid} (spot) issue {iid or '?'} needs spans as [start, end] offsets.")
            elif norm:
                for sp in spans:
                    if sp[1] > len(norm):
                        bad.append(f"{qid} (spot) issue {iid or '?'} has a span past the end of the fact text.")
                        break
        th = ans.get("threshold", 0.7)
        if not (isinstance(th, (int, float)) and 0 < th <= 1):
            bad.append(f"{qid} (spot) threshold must be between 0 and 1.")
    elif kind == "order":
        seq = ans.get("sequence")
        if not isinstance(seq, list) or len(seq) < 3:
            # Below three, a deranged bank still leaves too few arrangements to be a real recall act.
            bad.append(f"{qid} (order) needs a sequence of at least three elements.")
            seq = seq if isinstance(seq, list) else []
        bank_ids = {str(b.get("id")) for b in (ans.get("bank") or []) if isinstance(b, dict) and b.get("id")}
        if bank_ids:
            missing = [str(x) for x in seq if str(x) not in bank_ids]
            if missing:
                bad.append(f"{qid} (order) sequence names ids not in the bank: {', '.join(missing)}.")
    elif kind == "slot":
        elems = {str(e.get("id")) for e in (ans.get("elements") or []) if isinstance(e, dict) and e.get("id")}
        facts = {str(f.get("id")) for f in (ans.get("facts") or []) if isinstance(f, dict) and f.get("id")}
        key = ans.get("key")
        if len(elems) < 2:
            # A single element makes every fact a free mark — there is nothing to discriminate.
            bad.append(f"{qid} (slot) needs at least two elements.")
        if not facts:
            bad.append(f"{qid} (slot) needs at least one fact.")
        if not isinstance(key, dict) or not key:
            bad.append(f"{qid} (slot) needs a non-empty fact->element key.")
            key = {}
        for f, e in key.items():
            if facts and str(f) not in facts:
                bad.append(f"{qid} (slot) key maps unknown fact {f!r}.")
            if elems and str(e) not in elems:
                bad.append(f"{qid} (slot) key maps fact {f!r} to unknown element {e!r}.")
    return bad


def validate(game, keys) -> list:
    """What is wrong with a game, as short sentences; empty when the player can run it and every citation is real."""
    if not isinstance(game, dict):
        return ["The writer did not return a game."]
    keys, bad = set(keys), []
    if not str(game.get("title") or "").strip():
        bad.append("No title.")
    scenes = game.get("scenes") if isinstance(game.get("scenes"), list) else []
    phases = [s.get("phase") for s in scenes if isinstance(s, dict)]
    if not phases or phases[0] != "arrival" or phases.count("arrival") != 1:
        bad.append("The game must open with exactly one arrival scene.")
    if "verdict" not in phases:
        bad.append("No verdict scene.")
    order = [PHASES.index(p) if p in PHASES else -1 for p in phases]
    if -1 in order or order != sorted(order):
        bad.append("Scenes are out of order (arrival, examination, verdict, epilogue).")
    rounds = [s for s in scenes if isinstance(s, dict) and s.get("quiz")]
    if not MIN_ROUNDS <= len(rounds) <= MAX_ROUNDS:
        bad.append(f"{len(rounds)} examination round(s); a game has {MIN_ROUNDS} to {MAX_ROUNDS}.")
    for s in scenes:
        if not isinstance(s, dict):
            continue
        if s.get("set") not in SET_KINDS:
            bad.append(f"Scene {s.get('id', '?')} uses an unknown set {s.get('set')!r}.")
        if s.get("phase") == "arrival" and s.get("set") not in ARRIVAL_SETS:
            bad.append(f"The arrival must be outdoors ({' or '.join(ARRIVAL_SETS)}).")
        q = s.get("quiz")
        if not q:
            continue
        qid = q.get("id", "A quiz")
        kind = str(q.get("kind") or "mcq").lower()
        if not str(q.get("question") or "").strip():
            bad.append(f"{qid} has no question.")
        if kind == "mcq":
            opts = q.get("options") if isinstance(q.get("options"), list) else []
            if [o.get("key") for o in opts] != list(KEYS):
                bad.append(f"{qid} needs four options, A to D.")
            if sum(1 for o in opts if o.get("correct") is True) != 1:
                bad.append(f"{qid} must have exactly one correct option.")
            for o in opts:
                if not str(o.get("teaching") or "").strip():
                    bad.append(f"{qid} option {o.get('key', '?')} has no teaching text.")
        elif kind in PRODUCE_KINDS:
            # Produce-type: carries a cached `answer` and MUST NOT carry `options` (an options list of
            # >=2 is what the retrieval gate reads as recognition — the whole point is generation).
            if q.get("options") is not None:
                bad.append(f"{qid} is a {kind} interaction and must not carry 'options'.")
            if not str(q.get("teaching") or "").strip():
                bad.append(f"{qid} ({kind}) has no teaching text.")
            bad += _validate_produce_answer(qid, kind, q)
        else:
            bad.append(f"{qid} has an unknown interaction kind {kind!r} (one of {', '.join(INTERACTION_KINDS)}).")
    cited = set()
    for text in [all_text(game)]:
        cited |= {m.group(1) for m in _CITE.finditer(text)}
    for s in scenes:
        if not isinstance(s, dict):
            continue
        q = s.get("quiz") or {}
        for o in q.get("options") or []:
            cited |= {_cite_key(c) for c in o.get("cites") or [] if _cite_key(c)}
        cited |= {_cite_key(c) for c in q.get("cites") or [] if _cite_key(c)}
    for c in game.get("checks") or []:
        cited |= {_cite_key(x) for x in (c.get("cites") or []) if _cite_key(x)}
    unknown = sorted(cited - keys)
    if unknown:
        bad.append("Cites sources that do not exist: " + ", ".join(unknown) + ".")
    if not cited:
        bad.append("Nothing in the game is cited to his files.")
    irac = (game.get("verdict") or {}).get("irac")
    if not irac:
        bad.append("The verdict has no IRAC.")
    return bad


def finish(game: dict, gid: str, code: str, keyed: dict) -> dict:
    """The game as the player reads it: an id, the course code, the sources legend, and nothing left undefined."""
    g = dict(game)
    g["id"], g["course"] = gid, code
    g["sources"] = sources_json(keyed)
    g.setdefault("bible", {"palette": [], "mood": "", "notes": []})
    g.setdefault("removed", []); g.setdefault("coordinator_notes", []); g.setdefault("checks", [])
    for s in g.get("scenes") or []:
        s.setdefault("action", []); s.setdefault("dialogue", []); s.setdefault("shots", []); s.setdefault("quiz", None)
        s.setdefault("slug", {"int_ext": "INT" if s.get("set") not in ARRIVAL_SETS else "EXT", "place": "", "time": ""})
        for d in s["dialogue"]:
            d.setdefault("cites", [])
        q = s.get("quiz")
        if q:
            for o in q.get("options") or []:
                o.setdefault("cites", []); o.setdefault("story", ""); o.setdefault("outcome_title", "")
                o["stamp"] = "SUSTAINED" if o.get("correct") else "OVERRULED"
    return g


def interactions_from_game(game: dict) -> list:
    """Project a game's quizzes into the interaction list the studio retrieval_density gate scores.

    The player JSON has no `interactions` key; this derives it. One interaction per *productive act*:
    an mcq emits one recognition item carrying `options` (and its answer key); each produce-type act
    emits a generation item carrying an `answer` and NO `options`. An interaction is emitted only when
    its key is non-empty, so an empty answer never reads as non-retrieval and drags density down.
    """
    out = []
    for s in game.get("scenes") or []:
        if not isinstance(s, dict):
            continue
        q = s.get("quiz")
        if not q:
            continue
        qid = str(q.get("id") or s.get("id") or "q")
        kind = str(q.get("kind") or "mcq").lower()
        ans = q.get("answer") or {}
        if kind == "mcq":
            opts = q.get("options") if isinstance(q.get("options"), list) else []
            if len(opts) >= 2:
                correct = next((o.get("key") for o in opts if o.get("correct") is True), None)
                out.append({"id": qid, "kind": "mcq", "options": [o.get("key") for o in opts], "answer": correct})
        elif kind == "spot":
            for it in ans.get("issues") or []:
                if it.get("id") and it.get("spans"):
                    out.append({"id": f"{qid}:{it['id']}", "kind": "spot", "answer": {"spans": it["spans"], "tag": it["id"]}})
        elif kind == "order":
            if ans.get("sequence"):
                out.append({"id": qid, "kind": "order", "answer": list(ans["sequence"])})
        elif kind == "slot":
            for f, e in (ans.get("key") or {}).items():
                out.append({"id": f"{qid}:{f}", "kind": "slot", "answer": e})
    return out


def review_issues(review) -> list:
    """The reviewer's issues, cut to shape: [{where, problem, severity}]."""
    if not isinstance(review, dict):
        return []
    out = []
    for i in review.get("issues") or []:
        if isinstance(i, dict) and str(i.get("problem") or "").strip():
            sev = "high" if str(i.get("severity") or "").lower() == "high" else "low"
            out.append({"where": str(i.get("where") or "")[:80], "problem": str(i["problem"])[:400], "severity": sev})
    return out[:12]


def for_review(game: dict) -> str:
    """The parts of a game the reviewer judges: the questions, options, teaching and IRAC."""
    keep = {"title": game.get("title"), "case_file": game.get("case_file"), "rounds": [], "verdict": game.get("verdict")}
    for s in game.get("scenes") or []:
        if s.get("quiz"):
            keep["rounds"].append(s["quiz"])
    return json.dumps(keep, ensure_ascii=False)


# ---------------------------------------------------------------- when to write

def _inside_window(created, now: float, window_s: float) -> bool:
    """True when `created` is within `window_s` of `now`. A missing or unreadable `created` counts as
    inside (fail closed): a row we cannot date still uses a slot rather than freeing one."""
    try:
        return not now - float(created) >= window_s   # NaN compares False: inside too
    except (TypeError, ValueError):
        return True


def weekly_slots(rows: list, cap, now: float = None, window_s: float = SLOT_WINDOW_S):
    """Autonomous draft slots left this week, or None when there is no cap.

    `rows` are the owner's docket rows across ALL his courses ({status, created}); the cap is per owner, not per
    course (D-11). A row uses a slot when it is `writing`, `draft`, `approved` or `discarded`; a `failed` row
    (gate-blocked, gates unavailable or a broken writer) never does. With `now` given, only rows created within
    `window_s` of it count (a row with no readable `created` counts, fail closed); without it the caller has
    already filtered to the window in SQL."""
    if cap is None:
        return None
    used = 0
    for r in rows:
        if r.get("status") not in SLOT_STATUSES:
            continue
        if now is not None and not _inside_window(r.get("created"), now, window_s):
            continue
        used += 1
    return max(0, int(cap) - used)


def weeks_needing_games(files: list, games: list, now: float, failed_backoff_s: float = 6 * 3600,
                        max_failures: int = None, max_infra_failures: int = None, slots: int = None) -> list:
    """Weeks with material newer than their last game, oldest week first.

    `files` are the course's ticked text files ({week, created}); `games` its docket rows ({week, status,
    created, updated}). A week counts once any of its files is newer than the newest game for it, whatever
    that game's status: a discarded draft is not written again until new material arrives. A failed attempt
    holds the week back for a while so a broken week does not burn a model call on every visit.

    The three optional limits default to None, which is exactly the behaviour above. `max_failures` stops a
    week once that many failed rows whose `error` starts with GATE_BLOCKED were created after its newest file
    (one material version); new material resets the count. `max_infra_failures` does the same, separately,
    for GATE_UNAVAILABLE rows, so an outage does not spend the content quota. `slots` truncates the due list
    (oldest week first) to that many weeks; 0 queues nothing."""
    newest_file = {}
    for f in files:
        w = str(f.get("week") or "").strip()
        if w:
            newest_file[w] = max(newest_file.get(w, 0), f.get("created") or 0)
    newest_game, busy = {}, set()
    blocked, infra = {}, {}
    for g in games:
        w = str(g.get("week") or "").strip()   # same key as the file weeks above
        if g.get("status") == "writing" and now - (g.get("updated") or 0) < AUTO_STALE_S:
            busy.add(w)
        if g.get("status") == "failed" and (max_failures is not None or max_infra_failures is not None):
            if (g.get("created") or 0) > newest_file.get(w, 0):
                err = str(g.get("error") or "")
                if err.startswith(GATE_BLOCKED):
                    blocked[w] = blocked.get(w, 0) + 1
                elif err.startswith(GATE_UNAVAILABLE):
                    infra[w] = infra.get(w, 0) + 1
        if g.get("status") == "failed" and now - (g.get("updated") or 0) >= failed_backoff_s:
            continue
        newest_game[w] = max(newest_game.get(w, 0), g.get("created") or 0)
    spent = set()
    if max_failures is not None:
        spent |= {w for w, n in blocked.items() if n >= max_failures}
    if max_infra_failures is not None:
        spent |= {w for w, n in infra.items() if n >= max_infra_failures}
    due = [w for w, t in newest_file.items() if w not in busy and w not in spent and t > newest_game.get(w, 0)]
    due = sorted(due, key=lambda w: (int(w) if w.isdigit() else 999, w))
    return due if slots is None else due[:max(0, int(slots))]


# ================================================================ WRITER v2 (Game Studio model-quality plan, rungs 0-2)
# Opt-in (run.py CF_DOCKET_WRITER=v2, M4 writer only); everything above is v1 and unchanged.
# - code, not the model, picks the round mix (MIXES) and validate_v2 rejects a game off the mix or below
#   generation_ratio 0.4 (S13);
# - the writer returns a simple intermediate shape; compile_game builds the player JSON (spot offsets, ids, keys);
# - every wrong option states its `flaw`; the reviewer is told wrong options are wrong on purpose and returns
#   location + verbatim source quote, never a suggested fix;
# - every checks[] entry cites a numbered source sentence id (or a short range); code copies that exact text in as
#   its `quote` (numbered_sentence_checks), then verifies it (injected `quote_problems`) - the writer never types quotes;
# - the prompt is laid out as system = STUDIO_BRIEF, user = shared prefix (course brief, lexicon, sources) + ROLE
#   TASK last, so every role shares the M4 prefix cache.
# The pipeline is pure: the model calls are injected callables, so run.py and the M4 kit's best-of-N share it.

import hashlib

PROMPT_VERSION = "writer-v2.4"           # 2.1: checks cite numbered sentence ids, code inserts the quote;
                                         # 2.2: the prompt says "cites" takes source ids only, sentence ids go in "sentence"
                                         # 2.3: one targeted repair (exact check text, fix only that) after the repair round
                                         # 2.4: both repairs restate the writer contract (plan, shapes, option and id
                                         #      rules); labels keep the sources' threshold words; a round with no
                                         #      "kind" takes its planned kind; the targeted repair starts from the
                                         #      better of write/repair
MIN_GEN_RATIO = 0.4
MIXES = {                          # model-quality plan rung 0 item 3; every mix clears generation_ratio 0.4
    "A": ("mcq", "slot", "spot"),
    "B": ("mcq", "slot", "order"),
    "C": ("mcq", "mcq", "slot"),
    "D": ("mcq", "mcq", "spot"),
}
MIN_SLOT_FACTS, MIN_SPOT_ISSUES, MIN_ORDER_STEPS = 3, 2, 3
CHUNK_CHARS = 2_000                # passage size for ranked sources
GAP = "\n[…]\n"


def pick_mix(salt) -> str:
    """The round mix for one draft, chosen by code from MIXES (stable for a salt, spread across salts)."""
    keys = sorted(MIXES)
    return keys[int(hashlib.sha256(str(salt).encode("utf-8")).hexdigest(), 16) % len(keys)]


_ROUND_SHAPES = {
    "mcq": """  {"kind": "mcq", "topic": "...", "set": "courtroom", "dialogue": [{"speaker": "JUDGE <NAME>", "line": "..."}],
   "question": "an exam-shaped question that applies the rule to the case facts",
   "options": [
     {"key": "A", "text": "...", "correct": false, "flaw": "the one mistake this option makes", "mistake": "Short name of the mistake", "teaching": "why THIS option fails [KEY]"},
     {"key": "B", "text": "...", "correct": true, "teaching": "why this scores [KEY]"},
     {"key": "C", "text": "...", "correct": false, "flaw": "...", "mistake": "...", "teaching": "..."},
     {"key": "D", "text": "...", "correct": false, "flaw": "...", "mistake": "...", "teaching": "..."}],
   "cites": ["KEY"]}""",
    "slot": """  {"kind": "slot", "topic": "...", "set": "courtroom", "dialogue": [{"speaker": "...", "line": "..."}],
   "question": "Map each fact onto the element of the test it satisfies.",
   "elements": ["the first element, worded as the SOURCES state it", "the second element, likewise"],
   "facts": [{"fact": "a fact from the case file", "element": "the first element, worded as the SOURCES state it"}, {"fact": "...", "element": "the second element, likewise"}, {"fact": "...", "element": "..."}],
   "teaching": "why each fact satisfies its element [KEY]", "cites": ["KEY"]}""",
    "spot": """  {"kind": "spot", "topic": "...", "set": "courtroom", "dialogue": [{"speaker": "...", "line": "..."}],
   "question": "Highlight each passage that raises a distinct legal issue.",
   "text": "a short fact pattern, 3-6 sentences",
   "issues": [{"label": "the issue, worded as the SOURCES state the test", "phrase": "an EXACT phrase copied from text"}, {"label": "...", "phrase": "..."}],
   "teaching": "the issues and why they arise [KEY]", "cites": ["KEY"]}""",
    "order": """  {"kind": "order", "topic": "...", "set": "courtroom", "dialogue": [{"speaker": "...", "line": "..."}],
   "question": "Put the steps of the test in the order the course applies them.",
   "steps": ["first step", "second step", "third step"],
   "teaching": "why this order [KEY]", "cites": ["KEY"]}""",
}


def _shapes(mix: str) -> list:
    """The JSON shape of each distinct round kind in this mix, in plan order."""
    shapes = []
    for k in MIXES[mix]:
        if _ROUND_SHAPES[k] not in shapes:
            shapes.append(_ROUND_SHAPES[k])
    return shapes


def contract_rules(mix: str) -> str:
    """The writer contract every writer-side call carries: the code-picked round plan, minimums, the mcq option rule,
    label wording and the two kinds of id. writer_task opens with it; both repair prompts restate it with the round
    shapes (pilot 2026-11-12: repairs that only said "same round plan" collapsed a slot/spot game into mcq)."""
    kinds = MIXES[mix]
    plan = ", ".join(f"round {i}: {k}" for i, k in enumerate(kinds, 1))
    return f"""ROUND PLAN, chosen for you (follow it exactly, in this order): {plan}.
Every round carries its "kind" exactly as the plan names it, and uses that kind's fields (shown below).
Minimums: slot has at least {MIN_SLOT_FACTS} facts and 2 elements; spot has at least {MIN_SPOT_ISSUES} issues; order has at least {MIN_ORDER_STEPS} steps.
Every mcq round has exactly four options, keys A, B, C and D, and exactly one has "correct": true.
Every wrong mcq option has a "flaw" (the one real student mistake it makes) and its own teaching; no two options share teaching.
Slot elements and spot issue labels name the test as the SOURCES state it, keeping every qualifier and threshold word
the SOURCES attach to it; never shorten a test to a bare name. A slot fact describes what happened and never repeats the
name of the element it satisfies.
Every SOURCES sentence is numbered, like [S1.47]. Two kinds of id, never mixed:
- a SOURCE id is the file key alone (S1, S2): it is the only thing that goes in any "cites" list (["S1"], never
  ["S1.47"]) and in [S1] markers in text (teaching, rule, lines);
- a SENTENCE id (S1.47) goes ONLY in a check's "sentence" field, never in "cites" and never in text. "sentence" is
  the id of the ONE source sentence that states the check's claim ("S1.47"), or a range of at most
  {MAX_RANGE_SENTENCES} neighbouring sentences ("S1.47-S1.48"); never a claim, a paraphrase or a quote.
Do NOT type quotes: the code copies the sentence and fills in the check's source. Each check cites different sentences.
Order "steps" are given in the CORRECT order (the game shuffles them). Spot "phrase" must be copied exactly from "text"."""


def _contract_block(mix) -> str:
    """The contract plus round shapes, appended to a repair prompt; empty for an unknown mix (old callers)."""
    if mix not in MIXES:
        return ""
    return ("\n\nTHE WRITER CONTRACT (unchanged; the fixed game must still meet all of it):\n" + contract_rules(mix)
            + f"\nThe \"rounds\" list has exactly {len(MIXES[mix])} entries. Round shapes:\n"
            + "\n".join(_shapes(mix)))


def writer_task(label: str, mix: str, *, course_name: str = "", lawnote: str = "", exemplars: str = "") -> str:
    """The writer's ROLE TASK (last in the user message): the shape for exactly the kinds of this mix."""
    kinds = MIXES[mix]
    shapes = _shapes(mix)
    ex = f"\n\n{exemplars}" if exemplars else ""
    return f"""TASK (writer): write ONE game{f' for {course_name}' if course_name else ''} covering {label}.{lawnote}

{contract_rules(mix)}{ex}

Return ONLY this JSON (no prose, no code fence):
{{
 "title": "The <Short Evocative Case Name>",
 "logline": "2-3 sentences: who the client is, what went wrong, what the lawyer must show tonight",
 "learning_goal": "By the end, the player can: 1. ... 2. ... 3. ...",
 "case_file": ["Claimant: ...", "Respondent: ...", "Key fact: ...", "Key fact: ..."],
 "arrival": {{"place": "...", "action": ["what the player sees and does"], "dialogue": [{{"speaker": "NAME", "line": "..."}}]}},
 "rounds": [
{(','+chr(10)).join(shapes)}
 ],
 "verdict": {{"outcome": "WON", "dialogue": [{{"speaker": "JUDGE <NAME>", "line": "..."}}],
             "irac": [{{"issue": "...", "rule": "... [KEY]", "application": "...", "conclusion": "..."}}],
             "takeaway": "one line to remember for the exam"}},
 "epilogue": {{"action": ["..."]}},
 "checks": [{{"claim": "a legal claim the game relies on", "sentence": "S1.47"}}]
}}
The "rounds" list has exactly {len(kinds)} entries, one per round of the plan. Dialogue is short and spoken (3-6 lines),
speakers in CAPITALS, the same names throughout. 1 to 3 checks per round."""


def reviewer_task(game_json: str) -> str:
    return f"""TASK (reviewer): check the GAME below against the SOURCES above.
The [S1.47] tags in the SOURCES are sentence labels, not source text; a check's "sentence" names the sentence it rests on.
In every multiple-choice round exactly one option is marked correct and the others are WRONG ON PURPOSE. Each wrong
option states its "flaw". A wrong option that makes its stated mistake is doing its job: never report it for being
wrong. Check instead that the stated flaw is the real error in that option.
Report "high" ONLY when:
- the option marked correct is not right under the SOURCES;
- a wrong option is in fact also right, or right in part, under the SOURCES (or its stated flaw is not an error);
- teaching, a slot mapping, a spot issue, an order step or the IRAC states law the SOURCES do not support, as fact.
Anything else (style, length, a missing nuance) is "low".
For each issue give where it is and a verbatim quote from the SOURCES that shows the problem (empty when the point
is that the SOURCES say nothing). Do NOT suggest a fix.
Return ONLY JSON: {{"verdict": "ok" | "fix", "issues": [{{"where": "round 1 option C", "problem": "...", "severity": "high" | "low", "quote": "..."}}]}}
Say {{"verdict": "ok", "issues": []}} when the game is sound.

GAME:
{game_json}"""


def revise_task(issues: list, game_json: str) -> str:
    return f"""TASK (revise): the reviewer found the problems below in your game. Return the whole game again in the same
JSON shape (same round plan), with every "high" problem fixed and nothing else changed. Use only the SOURCES; drop a
point rather than invent support for it. Keep each wrong option wrong on purpose, with its flaw.

ISSUES:
{json.dumps(issues, ensure_ascii=False)}

GAME:
{game_json}"""


def repair_task(problems: list, last: str, mix: str = None) -> str:
    """The repair round: the problems, the writer contract and round shapes for `mix`, then the last attempt."""
    return ("TASK (repair): your last attempt had these problems; return the whole game again, in the same JSON shape "
            "and round plan, with them fixed:\n- " + "\n- ".join(problems) + _contract_block(mix)
            + "\n\nLAST ATTEMPT:\n" + last[:30000])


def targeted_repair_task(problems: list, last: str, mix: str = None) -> str:
    """The one last-chance repair after the repair round still failed: the exact check text, fix only that. The
    contract is restated so a fix that needs a round's shape (or a sentence id) has the rule in front of it."""
    return ("TASK (targeted repair): your game below still fails these checks, quoted exactly as the checker reported "
            "them:\n- " + "\n- ".join(problems) + "\n\nFix ONLY these problems, and fix every one of them: returning "
            "the game unchanged fails again. Keep everything the checks do not name: every other round, option, sentence "
            "id and check, in the same JSON shape and round plan. Return the whole corrected game as JSON."
            + _contract_block(mix) + "\n\nYOUR GAME:\n" + last[:30000])


class ChecksFailed(ValueError):
    """The game still fails the writer checks after the repair round (and the targeted repair, if one was made).
    Carries the counters the best-of-N eval reads; the message keeps the old 'did not pass the checks' prefix.
    `stages` is the full problem list after each writer call ([{"stage": "write" | "repair" | "repair_targeted",
    "problems": [...]}]) so a failed candidate can be diagnosed without the message's first four problems."""

    def __init__(self, msg: str, *, repair_attempted: bool = False, calls: list = None, stages: list = None):
        super().__init__(msg)
        self.repair_attempted, self.repaired, self.calls = repair_attempted, False, list(calls or [])
        self.stages = list(stages or [])


# ---------------------------------------------------------------- parsing and compiling

_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def parse_json_tolerant(text):
    """The JSON object in a model reply: code fences and a sentence around it are tolerated, and trailing commas
    are stripped before a second try (the probe's only parse failure). None when there is no object."""
    t = str(text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    body = t[a:b + 1]
    for cand in (body, _TRAILING_COMMA.sub(r"\1", body)):
        try:
            obj = json.loads(cand)
            return obj if isinstance(obj, dict) else None
        except ValueError:
            continue
    return None


def _slug_id(s, i) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:30]
    return s or f"x{i}"


def compile_game(g, mix: str = None):
    """(player JSON, problems) from the writer's intermediate shape. Problems are short sentences for the repair
    round. Python, not the model, computes spot offsets, ids, taxonomy, slot keys and order sequences."""
    if not isinstance(g, dict):
        return None, ["The writer did not return a JSON object."]
    probs = []
    rounds = g.get("rounds") if isinstance(g.get("rounds"), list) else []
    plan = list(MIXES[mix]) if mix in MIXES else None
    kinds = []
    for n, r in enumerate(rounds, 1):
        r = r if isinstance(r, dict) else {}
        k = str(r.get("kind") or "").strip().lower()
        if not k and plan and len(rounds) == len(plan) and plan[n - 1] == "mcq":
            k = "mcq"                  # a kind-less round planned as mcq is mcq, exactly as before v2.4: no new failure
        elif k not in INTERACTION_KINDS and plan and len(rounds) == len(plan):
            # No usable "kind" (missing or renamed): compile the round as the planned kind and say so, instead of the
            # old silent "mcq" default whose cascade ("needs four options") sent the repair after the wrong problem.
            probs.append(f"Round {n} has {'no' if not k else 'an unknown'} \"kind\"{f' ({k!r})' if k else ''}; the plan "
                         f"makes it a {plan[n - 1]} round: give it \"kind\": \"{plan[n - 1]}\" and the {plan[n - 1]} fields.")
            k = plan[n - 1]
        kinds.append(k or "mcq")
    if plan and kinds != plan:
        probs.append(f"The round plan is {', '.join(plan)}; you wrote {', '.join(kinds) or 'no rounds'}.")
        for n, (want, got) in enumerate(zip(plan, kinds), 1):
            if want != got:
                probs.append(f"Round {n} must be a {want} round, in the {want} shape, not {got}.")
    arr = g.get("arrival") if isinstance(g.get("arrival"), dict) else {}
    scenes = [{"id": "s1", "title": "Arrival + Briefing", "phase": "arrival", "set": "street",
               "slug": {"int_ext": "EXT", "place": str(arr.get("place") or ""), "time": "DUSK, WET"},
               "action": list(arr.get("action") or []), "dialogue": list(arr.get("dialogue") or [])}]
    for n, r in enumerate(rounds, 1):
        r = r if isinstance(r, dict) else {}
        kind, qid = kinds[n - 1], f"q{n}"
        q = {"id": qid, "question": str(r.get("question") or ""), "cites": list(r.get("cites") or [])}
        if kind == "mcq":
            opts = []
            for o in r.get("options") or []:
                o = o if isinstance(o, dict) else {}
                right = o.get("correct") is True
                opts.append({"key": o.get("key"), "text": str(o.get("text") or ""), "correct": right,
                             "flaw": "" if right else str(o.get("flaw") or ""),
                             "outcome_title": "" if right else str(o.get("mistake") or o.get("flaw") or ""),
                             "story": str(o.get("story") or ""), "teaching": str(o.get("teaching") or ""),
                             "cites": sorted({m.group(1) for m in _CITE.finditer(str(o.get("teaching") or ""))})
                             or list(r.get("cites") or [])})
            q["options"] = opts
        elif kind == "slot":
            els = [str(e) for e in r.get("elements") or []]
            eid = {e: f"e{i}" for i, e in enumerate(els, 1)}
            facts, key = [], {}
            for i, f in enumerate(r.get("facts") or [], 1):
                f = f if isinstance(f, dict) else {}
                fid = f"f{i}"
                facts.append({"id": fid, "label": str(f.get("fact") or "")})
                if f.get("element") in eid:
                    key[fid] = eid[f["element"]]
                else:
                    probs.append(f"{qid} (slot): fact {i} maps to {f.get('element')!r}, which is not one of its elements.")
            if len(facts) < MIN_SLOT_FACTS:
                probs.append(f"{qid} (slot) needs at least {MIN_SLOT_FACTS} facts.")
            q.update(kind="slot", teaching=str(r.get("teaching") or ""),
                     answer={"elements": [{"id": eid[e], "label": e} for e in els], "facts": facts, "key": key})
        elif kind == "spot":
            text = _norm_text(r.get("text"))
            issues, taxo = [], []
            for i, it in enumerate(r.get("issues") or [], 1):
                it = it if isinstance(it, dict) else {}
                ph = _norm_text(it.get("phrase")).strip()
                at = text.find(ph) if ph else -1
                if at < 0:
                    probs.append(f"{qid} (spot): issue {i} phrase {ph[:60]!r} is not an exact phrase of the fact text.")
                    continue
                iid = _slug_id(it.get("label"), i)
                while iid in {x["id"] for x in issues}:
                    iid += f"-{i}"
                issues.append({"id": iid, "label": str(it.get("label") or ""), "spans": [[at, at + len(ph)]]})
                taxo.append({"id": iid, "label": str(it.get("label") or "")})
            if len(issues) < MIN_SPOT_ISSUES:
                probs.append(f"{qid} (spot) needs at least {MIN_SPOT_ISSUES} issues found in its text.")
            q.update(kind="spot", text=text, teaching=str(r.get("teaching") or ""),
                     answer={"issues": issues, "taxonomy": taxo, "threshold": 0.7})
        elif kind == "order":
            bank = [{"id": f"e{i}", "label": str(s)} for i, s in enumerate(r.get("steps") or [], 1)]
            q.update(kind="order", teaching=str(r.get("teaching") or ""),
                     answer={"sequence": [b["id"] for b in bank], "bank": bank})
        else:
            probs.append(f"{qid}: unknown kind {kind!r}.")
        st = r.get("set") if r.get("set") in ("courtroom", "office", "parliament", "classroom") else "courtroom"
        scenes.append({"id": f"s{n + 1}", "title": f"Examination - {r.get('topic') or ''}".strip(" -"),
                       "phase": "examination", "set": st, "action": list(r.get("action") or []),
                       "dialogue": list(r.get("dialogue") or []), "quiz": q})
    v = g.get("verdict") if isinstance(g.get("verdict"), dict) else {}
    k = len(scenes) + 1
    scenes.append({"id": f"s{k}", "title": "Verdict", "phase": "verdict", "set": "courtroom", "action": [],
                   "dialogue": list(v.get("dialogue") or [])})
    scenes.append({"id": f"s{k + 1}", "title": "Epilogue", "phase": "epilogue", "set": "generic",
                   "action": list(((g.get("epilogue") or {}) if isinstance(g.get("epilogue"), dict) else {}).get("action") or []),
                   "dialogue": []})
    out = {k2: g.get(k2) for k2 in ("title", "logline", "learning_goal", "case_file")}
    out["scenes"] = scenes
    out["verdict"] = {"outcome": v.get("outcome", "WON"), "irac": v.get("irac") or [], "takeaway": v.get("takeaway", "")}
    out["checks"] = [{"n": i, **c} for i, c in enumerate(g.get("checks") or [], 1) if isinstance(c, dict)]
    return out, probs


# ---------------------------------------------------------------- the v2 checks

def generation_ratio(game: dict) -> float:
    items = interactions_from_game(game)
    return sum(1 for i in items if i["kind"] != "mcq") / len(items) if items else 0.0


def _first_mentions(text: str, labels: list):
    low = str(text or "").lower()
    pos = [low.find(str(l).lower().strip()) for l in labels]
    return None if any(p < 0 for p in pos) or not labels else sorted(range(len(labels)), key=lambda i: pos[i])


def validate_v2(game, keys, mix: str = None) -> list:
    """validate() plus the v2 rules: the code-picked round plan, generation_ratio >= MIN_GEN_RATIO, distinct
    teaching per option, a flaw and outcome title on every wrong option, an order key that agrees with its own
    teaching, and a quote on every check."""
    bad = validate(game, keys)
    if not isinstance(game, dict):
        return bad
    rounds = [s.get("quiz") for s in game.get("scenes") or [] if isinstance(s, dict) and s.get("quiz")]
    kinds = [str(q.get("kind") or "mcq").lower() for q in rounds]
    if mix in MIXES and kinds != list(MIXES[mix]):
        bad.append(f"The round plan is {', '.join(MIXES[mix])}, not {', '.join(kinds) or 'none'}.")
    ratio = generation_ratio(game)
    if ratio < MIN_GEN_RATIO:
        bad.append(f"Only {ratio:.0%} of the gradable items are produced (spot/slot/order); at least "
                   f"{MIN_GEN_RATIO:.0%} must be.")
    for q in rounds:
        qid, kind = q.get("id", "A quiz"), str(q.get("kind") or "mcq").lower()
        if kind == "mcq":
            opts = q.get("options") if isinstance(q.get("options"), list) else []
            teach = [" ".join(str(o.get("teaching") or "").split()).lower() for o in opts]
            if len(set(teach)) < len(teach):
                same = [str(o.get("key", "?")) for o, t in zip(opts, teach) if teach.count(t) > 1]
                bad.append(f"{qid}: several options share the same teaching text (options {', '.join(same)}); each wrong "
                           f"option explains its own mistake.")
            for o in opts:
                if o.get("correct") is True:
                    continue
                if not str(o.get("flaw") or "").strip():
                    bad.append(f"{qid} option {o.get('key', '?')} is wrong but states no flaw.")
                if not str(o.get("outcome_title") or "").strip():
                    bad.append(f"{qid} option {o.get('key', '?')} has no mistake name.")
        elif kind == "order":
            bank = {b.get("id"): b.get("label") for b in (q.get("answer") or {}).get("bank") or [] if isinstance(b, dict)}
            labels = [bank.get(x) for x in (q.get("answer") or {}).get("sequence") or []]
            got = _first_mentions(q.get("teaching"), labels) if labels and all(labels) else None
            if got is not None and got != list(range(len(labels))):
                bad.append(f"{qid} (order): the teaching names the steps in a different order from the answer key.")
    for c in game.get("checks") or []:
        if isinstance(c, dict) and not c.get("unresolved") and not str(c.get("quote") or "").strip():
            bad.append(f"Check {c.get('n', '?')} has no quote from its source.")
    checks = [c for c in game.get("checks") or [] if isinstance(c, dict)]
    if rounds and len(checks) < len(rounds):     # one quoted claim cannot ground a whole game (adversarial review)
        bad.append(f"The game has {len(checks)} checks for {len(rounds)} rounds; give at least one quoted check per "
                   f"round.")
    return bad


_PAGE_CITE = re.compile(r"\[([A-Z][A-Z0-9]{0,5})\s+p{1,2}\.\s*([0-9]+)(?:\s*[-–]\s*[0-9]+)?\]")


def _page_known(text: str, page: str) -> bool:
    """True when the source text itself shows page N ("page 14", "p. 14", or a line that is just "14")."""
    return bool(re.search(rf"(?i)\b(?:page|p\.)\s*{re.escape(page)}\b|^[ \t\-]*{re.escape(page)}[ \t\-]*$",
                          text or "", re.MULTILINE))


def strip_unverifiable_pages(obj, keyed: dict):
    """A copy with every [KEY p.N] whose source shows no page N rewritten as [KEY]: a page the source does not show
    is invented (the dry run's page number was)."""
    def fix(s: str) -> str:
        return _PAGE_CITE.sub(lambda m: m.group(0) if _page_known((keyed.get(m.group(1)) or {}).get("text") or "",
                                                                  m.group(2)) else f"[{m.group(1)}]", s)
    if isinstance(obj, str):
        return fix(obj)
    if isinstance(obj, list):
        return [strip_unverifiable_pages(x, keyed) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_unverifiable_pages(v, keyed) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------- sources: hygiene and ranked passages

_VERSION_NOISE = re.compile(r"(\(\d+\)|\bcopy\b|\bv\d+\b|\bversion\s*\d+\b|\bchecked\b|\bfinal\b|\bdraft\b|[_\-\s.]+)")


def _stem(name: str) -> str:
    base = re.sub(r"\.[a-z0-9]{2,5}$", "", str(name or "").lower())
    return _VERSION_NOISE.sub(" ", base).strip()


def dedupe_versions(files: list) -> list:
    """One file per document: versions of the same name in the same week (copies, '(1)', 'v2', 'final', 'checked')
    collapse to the 'checked' one, else the newest. Order of first appearance is kept."""
    best, order = {}, []
    for f in files:
        s = (str(f.get("week") or ""), _stem(f.get("name")))   # same name in two weeks = two documents
        if s not in best:
            order.append(s)
            best[s] = f
            continue
        cur = best[s]
        rank = lambda x: ("checked" in str(x.get("name") or "").lower(), x.get("created") or 0)  # noqa: E731
        if rank(f) > rank(cur):
            best[s] = f
    return [best[s] for s in order]


def _chunks(text: str, size: int = CHUNK_CHARS) -> list:
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            k = text.rfind("\n\n", i + size // 2, j)
            j = k if k > i else j
        out.append((i, j))
        i = j
    return out


def ranked_sources_block(keyed: dict, query: str, rank=None) -> str:
    """The v2 writer's SOURCES: every file split into numbered sentences ("[S1.47] ..." one per line, see
    sentence_spans), so the writer cites a sentence id and code copies the quote (numbered_sentence_checks).
    A file over its share (FILE_CHARS, and the SOURCE_CHARS budget) keeps its most relevant passages, ranked
    against `query` (the course's exam / WG / standard-answer text), in their original order, with [...] marking
    cuts. No query (or no ranker): the first share of each file, as sources_block cuts it. Only whole sentences
    are shown: a sentence is shown when it starts inside a kept passage. Ids are numbered over the WHOLE file, so
    they do not depend on what was kept."""
    ranked = bool(str(query or "").strip()) and rank is not None
    parts, budget = [], SOURCE_CHARS
    for key, f in keyed.items():
        if budget <= 0:
            break
        text, cap = f.get("text") or "", min(FILE_CHARS, budget)
        if len(text) <= cap:
            kept = [(0, len(text))]
        elif not ranked:
            kept = [(0, cap)]
        else:
            spans = _chunks(text)
            scores = rank(query, [text[a:b] for a, b in spans])
            keep, used = set(), 0
            for i in sorted(range(len(spans)), key=lambda i: -scores[i]):
                n = spans[i][1] - spans[i][0]
                if used + n > cap:
                    continue
                keep.add(i)
                used += n
            kept = [spans[i] for i in sorted(keep)]
        lines, prev = [], None
        for n, (a, b) in enumerate(sentence_spans(text), 1):
            if not any(x <= a < y for x, y in kept):
                continue
            if prev is not None and n != prev + 1:
                lines.append(GAP.strip("\n"))
            lines.append(f"[{key}.{n}] " + " ".join(text[a:b].split()))
            prev = n
        body = "\n".join(lines)
        budget -= len(body)
        parts.append(f'<source key="{key}" file="{f.get("name", "")}" kind="{f.get("role") or f.get("kind") or ""}">\n{body}\n</source>')
    return "SOURCES:\n" + "\n\n".join(parts)


# ---------------------------------------------------------------- numbered sentences (the writer cites ids, code quotes)
# The local Coder paraphrased and stitched "verbatim" quotes (PIL wk4 pilot: 4/4 v2 drafts rejected). So the
# writer no longer types quotes: it cites a sentence id ("S1.47") or a short range ("S1.47-S1.49") from the
# numbered SOURCES, and code copies that exact source text in as the check's quote. studio.grounding then
# verifies it as before (6-word minimum, no reuse or near-duplicates), and it passes by construction.

MAX_SENTENCE_CHARS = 600           # a longer run of text (a slide with no full stops) is cut at a space
MAX_RANGE_SENTENCES = 3            # a check may cite one sentence or up to 3 contiguous ones
_ABBREV = {"cf", "v", "vs", "e.g", "i.e", "eg", "ie", "mr", "mrs", "ms", "dr", "prof", "ibid", "al", "op", "jr",
           "approx", "resp", "viz", "ecr", "jur", "rv"}        # never end a sentence
_NUM_ABBREV = {"art", "arts", "p", "pp", "para", "paras", "no", "nos", "nr", "ch", "ss", "reg", "dir", "vol", "fig",
               "sec", "par", "sub", "lit", "oj", "nrs"}         # do not end one when a number follows ("Art. 5")
_SENT_END = re.compile(r"[.!?]+[\"'\u201d\u2019)\]]*(?=\s)")
_NEXT_START = re.compile(r"\s+(?=[\"'\u201c\u2018(\[]?[A-Z0-9\u00c0-\u00de\u2022\-\u2013*])")
_BULLET_LINE = re.compile(r"\n[ \t]*(?:[\u2022\u25aa\u25cf\u25e6\-\u2013*>]|\(?[0-9]{1,2}[.)]|\(?[a-z][.)]|\([ivx]{1,4}\))[ \t]")
_PARA = re.compile(r"\n[ \t]*\n")
_TAGGED_LINE = re.compile(r"(?m)^\[([A-Z][A-Z0-9]{0,5})\.([0-9]+)\] ")
_SENT_REF = re.compile(r"^\[?\s*([A-Z][A-Z0-9]{0,5})\.([0-9]+)\s*(?:[-\u2013\u2014]|to)\s*(?:([A-Z][A-Z0-9]{0,5})\.)?([0-9]+)\s*\]?$"
                       r"|^\[?\s*([A-Z][A-Z0-9]{0,5})\.([0-9]+)\s*\]?$")
_ONE_SENT = r"[A-Z][A-Z0-9]{0,5}\.[0-9]+(?:\s*[-\u2013\u2014]\s*(?:[A-Z][A-Z0-9]{0,5}\.)?[0-9]+)?"
# "[S1.47]", "[S1.4-S1.6]", and a list in one bracket "[S1.18, S2.3]" / "[S1.4; S1.6-S1.7]"
_INLINE_SENT_CITE = re.compile(r"\[(" + _ONE_SENT + r"(?:\s*[,;]\s*" + _ONE_SENT + r")*)\]")
_SENT_ID_SHAPE = re.compile(r"^\[?\s*[A-Z][A-Z0-9]{0,5}\.[0-9]")   # looks like a sentence id, not a source key


_SENT_FIELDS = ("sentence", "sentences", "sentence_ids")


def _cut_long(text: str, a: int, b: int) -> list:
    out = []
    while b - a > MAX_SENTENCE_CHARS:
        k = max(text.rfind(" ", a + MAX_SENTENCE_CHARS // 2, a + MAX_SENTENCE_CHARS),
                text.rfind("\n", a + MAX_SENTENCE_CHARS // 2, a + MAX_SENTENCE_CHARS))
        k = k if k > a else a + MAX_SENTENCE_CHARS
        out.append((a, k))
        a = k
    out.append((a, b))
    return out


def sentence_spans(text: str) -> list:
    """[(start, end)] of every sentence of `text`, in order: the stable numbering behind sentence ids (id n is
    span n-1). A paragraph break, a bullet / numbered line, or [.!?] followed by a capital or digit ends a
    sentence; a full stop after a legal abbreviation ("Art.", "p.", "v.", "e.g.") or an initial does not. Each span
    is trimmed of surrounding whitespace and has a letter or digit; runs over MAX_SENTENCE_CHARS are cut at a space.
    Deterministic, stdlib only."""
    text = str(text or "")
    cuts = {0, len(text)}
    for m in _PARA.finditer(text):
        cuts.add(m.start())
    for m in _BULLET_LINE.finditer(text):
        cuts.add(m.start())
    for m in _SENT_END.finditer(text):
        nxt = _NEXT_START.match(text, m.end())
        if not nxt:
            continue
        if text[m.start()] == ".":
            w = re.search(r"([^\W\d_][\w.]*)$", text[max(0, m.start() - 12):m.start()])
            word = (w.group(1) if w else "").lower()
            if word in _ABBREV or (w and len(w.group(1)) == 1) or (word in _NUM_ABBREV and text[nxt.end()].isdigit()):
                continue
            if re.fullmatch(r"[ \t]*\(?[0-9]{1,3}|[ \t]*\(?[ivx]{1,4}", text[text.rfind("\n", 0, m.start()) + 1:m.start()]):
                continue                                          # "1. First step": a list number, not an end
        cuts.add(m.end())
    out, edges = [], sorted(cuts)
    for a, b in zip(edges, edges[1:]):
        seg = text[a:b]
        lead = len(seg) - len(seg.lstrip())
        a2, b2 = a + lead, a + len(seg.rstrip())
        if b2 <= a2 or not re.search(r"[^\W_]", text[a2:b2]):
            continue
        out.extend(_cut_long(text, a2, b2))
    return out


def shown_sentence_ids(prefix: str) -> set:
    """{(key, n)} of every sentence id tag the writer was shown (line-start "[S1.47] " in the prompt prefix)."""
    return {(m.group(1), int(m.group(2))) for m in _TAGGED_LINE.finditer(str(prefix or ""))}


def _parse_sentence_ref(ref):
    """(key, first, last) from "S1.47", "[S1.47]", "S1.47-S1.49", "S1.47-49" or ["S1.47", "S1.49"]; None if
    malformed, ("", 0, 0) if a list mixes sources."""
    if isinstance(ref, list):
        ref = [str(x).strip() for x in ref if str(x).strip()]
        if len(ref) == 1:
            ref = ref[0]
        elif ref:
            ends = [_parse_sentence_ref(x) for x in ref]
            if any(e is None for e in ends):
                return None
            keys, ns = {e[0] for e in ends}, sorted(n for e in ends for n in (e[1], e[2]))
            if len(keys) != 1:
                return "", 0, 0
            if len(ref) > 2 and ns != list(range(ns[0], ns[0] + len(ns))):
                return None                                      # a list of ids must be contiguous
            return keys.pop(), ns[0], ns[-1]
        else:
            return None
    m = _SENT_REF.match(str(ref or "").strip())
    if not m:
        return None
    if m.group(5):
        return m.group(5), int(m.group(6)), int(m.group(6))
    if m.group(3) and m.group(3) != m.group(1):
        return "", 0, 0
    return m.group(1), int(m.group(2)), int(m.group(4))


def numbered_sentence_checks(checks, keyed: dict, shown=None):
    """(checks, problems): each check's sentence id (or short range) resolved to the exact source text, which
    becomes its `quote`; its `cites` become that id's source key. Any quote the model typed is discarded. A check
    whose id is missing, malformed, unknown, not shown to the writer (`shown`, from shown_sentence_ids; None = any
    id in the file), reversed, over MAX_RANGE_SENTENCES, across two sources, or overlapping an earlier check's
    sentences gets a problem and is marked `unresolved` (studio.grounding skips it: one problem per check)."""
    out, bad, used, idx = [], [], set(), {}
    for i, c in enumerate(checks if isinstance(checks, list) else [], 1):
        if not isinstance(c, dict):
            out.append(c)
            continue
        c = {k: v for k, v in c.items() if k not in ("quote", "unresolved")}
        n_ = c.get("n", i)
        ref = next((c[f] for f in _SENT_FIELDS if f in c), None)
        if ref in (None, "", []):          # no "sentence" but a sentence id in "cites": the same rules resolve it
            ids = [x for x in (c.get("cites") or []) if isinstance(x, str) and _SENT_ID_SHAPE.match(x.strip())]
            ref = ids[0] if len(ids) == 1 else (ids or ref)
        problem = None
        parsed = _parse_sentence_ref(ref) if ref not in (None, "", []) else None
        if ref in (None, "", []):
            problem = (f"check {n_} has no \"sentence\": give the id of the source sentence that states the claim "
                       f"(e.g. \"S1.12\", or a range of up to {MAX_RANGE_SENTENCES} like \"S1.12-S1.13\"); do not type a quote.")
        elif parsed is None:
            problem = (f"check {n_}: {str(ref)[:40]!r} is not a sentence id; use an id shown in the SOURCES, like "
                       f"\"S1.12\" or \"S1.12-S1.13\".")
        elif not parsed[0]:
            problem = f"check {n_}: the range {str(ref)[:40]!r} crosses two sources; cite sentences from one source."
        else:
            key, a, b = parsed
            if key not in keyed:
                problem = f"check {n_}: {key} is not a source key."
            else:
                if key not in idx:
                    idx[key] = sentence_spans((keyed[key] or {}).get("text") or "")
                spans = idx[key]
                if b < a:
                    problem = f"check {n_}: the range {key}.{a}-{key}.{b} runs backwards."
                elif b - a + 1 > MAX_RANGE_SENTENCES:
                    problem = (f"check {n_}: {key}.{a}-{key}.{b} is {b - a + 1} sentences; cite the one sentence that "
                               f"states the claim (a range of at most {MAX_RANGE_SENTENCES}).")
                elif a < 1 or b > len(spans) or (shown is not None and any((key, n) not in shown for n in range(a, b + 1))):
                    problem = (f"check {n_}: {key}.{a}" + (f"-{key}.{b}" if b != a else "")
                               + " is not a sentence shown in the SOURCES; cite an id you can see there.")
                elif any((key, n) in used for n in range(a, b + 1)):
                    problem = (f"check {n_}: {key}.{a}" + (f"-{key}.{b}" if b != a else "")
                               + " repeats a sentence an earlier check cites; each claim needs its own support.")
                else:
                    text = keyed[key].get("text") or ""
                    used.update((key, n) for n in range(a, b + 1))
                    c["sentence"] = f"{key}.{a}" + (f"-{key}.{b}" if b != a else "")
                    c["cites"] = [key]
                    c["quote"] = " ".join(text[spans[a - 1][0]:spans[b - 1][1]].split())
        if problem:
            bad.append(problem)
            c["unresolved"] = True
            if isinstance(c.get("cites"), list):   # one problem per check: S1.99 is reported here, not as a source
                c["cites"] = _source_cites(c["cites"])
        out.append(c)
    return out, bad


def _source_cites(cites) -> list:
    """A "cites" list with every sentence id or range ("S1.18", "[S1.18-S1.20]") replaced by its source key, in
    order, without duplicates. Anything that does not resolve (an unknown or cross-source ref) is kept as typed so
    validate() still reports it."""
    out = []
    for c in cites:
        k = _cite_key(c) if isinstance(c, str) else c
        if k not in ("", None) and k not in out:
            out.append(k)
    return out


def _collapse_inline(m) -> str:
    keys = []
    for part in re.split(r"\s*[,;]\s*", m.group(1)):
        k = _cite_key(part)
        if k not in keys:
            keys.append(k)
    return "".join(f"[{k}]" for k in keys)


def collapse_sentence_cites(obj, _in_checks: bool = False):
    """A copy with every sentence id that leaked out of a check's "sentence" rewritten as its source cite: inline
    ("[S1.47]", "[S1.4-S1.6]", "[S1.18, S2.3]") in player text becomes "[S1]" / "[S1][S2]", and "cites": ["S1.18"]
    becomes ["S1"] - ids belong in a check's "sentence", but a leaked one must still count as a citation of S1. The
    "sentence" fields are left alone, and so are the "cites" of checks: numbered_sentence_checks reads a sentence id
    there when the check has no "sentence", then sets them to the source key itself."""
    if isinstance(obj, str):
        return _INLINE_SENT_CITE.sub(_collapse_inline, obj)
    if isinstance(obj, list):
        return [collapse_sentence_cites(x, _in_checks) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _SENT_FIELDS:
                out[k] = v
            elif k == "cites" and isinstance(v, list):
                out[k] = list(v) if _in_checks else _source_cites(v)
            else:
                out[k] = collapse_sentence_cites(v, _in_checks or k == "checks")
        return out
    return obj


# ---------------------------------------------------------------- the pipeline

def review_issues_v2(review) -> list:
    """[{where, problem, severity, quote}] - no suggested fix is kept even if the model sends one."""
    out = []
    for i in review_issues(review):
        src = next((x for x in (review or {}).get("issues") or []
                    if isinstance(x, dict) and str(x.get("problem") or "")[:400] == i["problem"]), {})
        out.append({**i, "quote": str(src.get("quote") or "")[:400]})
    return out


def write_draft_v2(coder, *, system: str, prefix: str, label: str, mix: str, keyed: dict, reviewer=None,
                   course_name: str = "", lawnote: str = "", exemplars: str = "", unverified=None,
                   quote_problems=None, heartbeat=None) -> dict:
    """Write, check (one repair round, then one targeted repair), review on the Thinker and (once) revise one game.
    Pure orchestration.

    coder(role, system, user, max_tokens) -> (text, served_model, base)   the M4 Coder
    reviewer(role, system, user, max_tokens) -> (text, served_model, base) the M4 Thinker; None skips review
        (best-of-N gates candidates with the doctrine gate instead; the Coder never reviews its own game)
    unverified(player_game) -> [raw citation not found in the course files]
    quote_problems(checks, keyed) -> [problem]
    Returns {game (player JSON, not finished), intermediate, issues, unverified, revised, model, calls, mix,
    prompt_version, repair_attempted, repaired}. repair_attempted/repaired describe the targeted repair only (the
    first repair round runs on most drafts). Raises ChecksFailed (a ValueError) when the game still fails the checks
    after both."""
    if mix not in MIXES:
        raise ValueError(f"unknown round mix {mix!r}")
    calls = []
    beat = heartbeat or (lambda: None)

    def call(fn, role, task, max_tokens):
        text, served, base = fn(role, system, prefix + "\n\n" + task, max_tokens)
        calls.append({"role": role, "model": served, "base": base})
        beat()
        return text

    shown = shown_sentence_ids(prefix)

    def check(g):
        raw = g
        game, probs = compile_game(collapse_sentence_cites(g), mix)
        if game is None:
            return None, probs, [], []
        game = strip_unverifiable_pages(game, keyed)
        game["checks"], quotes = numbered_sentence_checks(game.get("checks") or [], keyed, shown)
        probs = probs + validate_v2(game, keyed.keys(), mix)
        gone = list(unverified(game)) if unverified else []
        quotes = quotes + (list(quote_problems(game.get("checks") or [], keyed)) if quote_problems else [])
        return game, probs, gone, quotes, raw

    stages = []
    nojson = (None, ["The writer did not return a JSON object."], [], [], None)

    def staged(stage, obj):
        r = check(obj) if obj is not None else nojson
        stages.append({"stage": stage, "problems": list(r[1]) + list(r[3])
                       + [f"'{x}' is not in the SOURCES" for x in r[2]]})
        return r

    task = writer_task(label, mix, course_name=course_name, lawnote=lawnote, exemplars=exemplars)
    inter = parse_json_tolerant(call(coder, "write", task, 12000))
    res = staged("write", inter)
    game, probs, gone, quotes = res[:4]
    if probs or gone or quotes:
        fix = probs + quotes + [f"'{x}' is not in the SOURCES: remove it or use what the sources say" for x in gone]
        first = (inter, game, probs, gone, quotes)
        inter = parse_json_tolerant(call(coder, "repair", repair_task(fix, json.dumps(inter, ensure_ascii=False)
                                                                       if inter is not None else "", mix), 12000))
        res = staged("repair", inter)
        game, probs, gone, quotes = res[:4]
        # A repair round can make a draft worse (pilot 2026-11-12: one collapsed a slot/spot game into mcq). Go back to
        # the first draft only when it still fails a hard check (so the targeted repair and check() still run on it)
        # and the repair parsed to nothing or left more problems, off-source citations counted on both sides; a
        # first draft whose only fault was an off-source citation is never kept over its repair.
        if first[0] is not None and (first[2] or first[4]) and (
                inter is None or len(probs) + len(quotes) + len(gone) > len(first[2]) + len(first[3]) + len(first[4])):
            inter, game, probs, gone, quotes = first
    # One targeted repair (pilot 2026-11-12: half the drafts died on one small slip left after the repair round): the
    # Coder gets its own last draft and the exact failing check text, once. Same check() after; nothing is skipped.
    repair_attempted = repaired = False
    if (game is None or probs or quotes) and inter is not None:
        repair_attempted = True
        fixed = parse_json_tolerant(call(coder, "repair_targeted", targeted_repair_task(
            probs + quotes, json.dumps(inter, ensure_ascii=False), mix), 12000))
        fres = staged("repair_targeted", fixed)
        if fixed is not None:
            if fres[0] is not None and not fres[1] and not fres[3]:
                inter, game, probs, gone, quotes, repaired = fixed, fres[0], fres[1], fres[2], fres[3], True
            else:
                probs, quotes = fres[1], fres[3]
        else:
            probs, quotes = ["The writer did not return a JSON object."], []
    if game is None or probs or quotes:
        raise ChecksFailed("The game did not pass the checks: " + " ".join((probs + quotes)[:4]),
                           repair_attempted=repair_attempted, calls=calls, stages=stages)
    issues, revised = [], False
    if reviewer is not None:
        issues = review_issues_v2(parse_json_tolerant(call(reviewer, "review",
                                  reviewer_task(json.dumps(inter, ensure_ascii=False)), 16000)))
        if any(i["severity"] == "high" for i in issues):
            fixed = parse_json_tolerant(call(coder, "revise", revise_task(issues, json.dumps(inter, ensure_ascii=False)), 12000))
            if fixed is not None:
                fres = check(fixed)
                if fres[0] is not None and not fres[1] and not fres[3]:
                    inter, game, gone, revised = fixed, fres[0], fres[2], True
                    issues = review_issues_v2(parse_json_tolerant(call(reviewer, "review",
                                              reviewer_task(json.dumps(inter, ensure_ascii=False)), 16000)))
    writer_model = next((c["model"] for c in reversed(calls)
                         if c["role"] in ("write", "repair", "repair_targeted", "revise")), "")
    return {"game": game, "intermediate": inter, "issues": issues, "unverified": gone, "revised": revised,
            "model": writer_model, "calls": calls, "mix": mix, "prompt_version": PROMPT_VERSION,
            "generation_ratio": generation_ratio(game), "repair_attempted": repair_attempted, "repaired": repaired}
