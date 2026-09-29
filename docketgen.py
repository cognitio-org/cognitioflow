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

SET_KINDS = ("customs_yard", "office", "courtroom", "street", "classroom", "parliament", "generic", "tv_studio")
ARRIVAL_SETS = ("street", "customs_yard")
PHASES = ("arrival", "examination", "verdict", "epilogue")
KEYS = "ABCD"
MIN_ROUNDS, MAX_ROUNDS = 2, 4
SOURCE_CHARS = 110_000            # what the writer reads from a week; past exams and WG material first
FILE_CHARS = 40_000               # no single reader may crowd the rest out
AUTO_STALE_S = 20 * 60            # a writing job not heard from in this long has died with its instance

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

_CITE = re.compile(r"\[([A-Z][A-Z0-9]{0,5})(?:\s+p{1,2}\.\s*[0-9]+(?:\s*[-–]\s*[0-9]+)?)?\]")


def _cite_key(c) -> str:
    return str(c).strip().strip("[]").split()[0] if str(c).strip() else ""


def all_text(game: dict) -> str:
    """Every word a player could read, for the citation check."""
    out = [game.get("title", ""), game.get("logline", ""), game.get("learning_goal", "")] + list(game.get("case_file") or [])
    for s in game.get("scenes") or []:
        out += list(s.get("action") or []) + [d.get("line", "") for d in s.get("dialogue") or []]
        q = s.get("quiz") or {}
        out.append(q.get("question", ""))
        for o in q.get("options") or []:
            out += [o.get("text", ""), o.get("story", ""), o.get("teaching", "")]
    v = game.get("verdict") or {}
    for r in v.get("irac") or []:
        out += [r.get(k, "") for k in ("issue", "rule", "application", "conclusion")]
    out.append(v.get("takeaway", ""))
    return "\n".join(str(x) for x in out if x)


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
        opts = q.get("options") if isinstance(q.get("options"), list) else []
        if [o.get("key") for o in opts] != list(KEYS):
            bad.append(f"{q.get('id', 'A quiz')} needs four options, A to D.")
        if sum(1 for o in opts if o.get("correct") is True) != 1:
            bad.append(f"{q.get('id', 'A quiz')} must have exactly one correct option.")
        if not str(q.get("question") or "").strip():
            bad.append(f"{q.get('id', 'A quiz')} has no question.")
        for o in opts:
            if not str(o.get("teaching") or "").strip():
                bad.append(f"{q.get('id', 'quiz')} option {o.get('key', '?')} has no teaching text.")
    cited = set()
    for text in [all_text(game)]:
        cited |= {m.group(1) for m in _CITE.finditer(text)}
    for s in scenes:
        for o in ((s.get("quiz") or {}).get("options") or []) if isinstance(s, dict) else []:
            cited |= {_cite_key(c) for c in o.get("cites") or [] if _cite_key(c)}
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

def weeks_needing_games(files: list, games: list, now: float, failed_backoff_s: float = 6 * 3600) -> list:
    """Weeks with material newer than their last game, oldest week first.

    `files` are the course's ticked text files ({week, created}); `games` its docket rows ({week, status,
    created, updated}). A week counts once any of its files is newer than the newest game for it, whatever
    that game's status: a discarded draft is not written again until new material arrives. A failed attempt
    holds the week back for a while so a broken week does not burn a model call on every visit."""
    newest_file = {}
    for f in files:
        w = str(f.get("week") or "").strip()
        if w:
            newest_file[w] = max(newest_file.get(w, 0), f.get("created") or 0)
    newest_game, busy = {}, set()
    for g in games:
        w = str(g.get("week") or "")
        if g.get("status") == "writing" and now - (g.get("updated") or 0) < AUTO_STALE_S:
            busy.add(w)
        if g.get("status") == "failed" and now - (g.get("updated") or 0) >= failed_backoff_s:
            continue
        newest_game[w] = max(newest_game.get(w, 0), g.get("created") or 0)
    due = [w for w, t in newest_file.items() if w not in busy and t > newest_game.get(w, 0)]
    return sorted(due, key=lambda w: (int(w) if w.isdigit() else 999, w))
