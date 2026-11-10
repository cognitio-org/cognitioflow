#!/usr/bin/env python3
"""Pre-fill the game caches OFFLINE so play-time never calls an external AI.

The games (recall quiz, the "Who Wants to Be a Lawyer?" arena, the hint lifeline and the "Cases" moot
hearing) each read a cache at play-time and only fall back to a model on a miss. This script fills
those caches ahead of time — an authoring-time step, the same side of the line as writing a game — so
that at play-time every request is a cache hit and no model is called on the student's request path.

It routes its own (authoring-time) generation through `ask_model(..., task=...)`, so with the local
M4 lane configured (CF_LOCAL_BASE_URL + CF_LOCAL_TASKS) it fills from the local model and spends
nothing. Run it after importing/editing cards, or on a schedule. It is NOT wired into card import
(that would put a synchronous model call back on a request) — see the PR's Needs-Matej list.

Usage:
    python scripts/prefill_game_caches.py                 # every course: distractors, hints, hearings
    python scripts/prefill_game_caches.py --course <cid>  # one course
    python scripts/prefill_game_caches.py --case "Dassonville" --case "Cassis"   # specific hearings
    python scripts/prefill_game_caches.py --calibrate --course <cid>             # grader score spread
    python scripts/prefill_game_caches.py --dry-run       # list what is missing, generate nothing
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run  # noqa: E402  — loads env, DB pool, and every helper/prompt the endpoints use


def _courses(cid):
    if cid:
        return [cid]
    return [r["id"] for r in run.rows("SELECT id FROM courses ORDER BY created")]


def fill_distractors(cid, dry=False):
    """Fill card_distractors for every card whose stored set is missing or stale, exactly as /quiz would."""
    cards = run.rows("SELECT id, front, back FROM cards WHERE course_id=?", cid)
    cached = {r["card_id"]: r for r in run.rows(
        "SELECT card_id, back_hash FROM card_distractors WHERE card_id IN "
        "(SELECT id FROM cards WHERE course_id=?)", cid)}
    need = [c for c in cards if not (cached.get(c["id"]) and cached[c["id"]]["back_hash"] == run._distractor_hash(c["back"]))]
    if not need:
        return 0
    if dry:
        print(f"  distractors: {len(need)} card(s) missing")
        return len(need)
    others = [c["back"][:200] for c in cards]
    filled = 0
    for batch in (need[i:i + 20] for i in range(0, len(need), 20)):
        got = run._model_json(run.ask_model(run.CHEAP_MODEL, task="quiz", max_tokens=3000,
                                            messages=[{"role": "user", "content": run._distractor_prompt(batch, others)}]))
        by_i = {}
        for x in got if isinstance(got, list) else []:
            if isinstance(x, dict) and isinstance(x.get("wrong"), list):
                try: by_i[int(x["i"])] = x["wrong"]
                except Exception: continue
        with run.db() as d:
            for i, c in enumerate(batch):
                valid = run._valid_wrong(by_i.get(i), c["back"].strip())
                if not valid:
                    continue
                d.execute("INSERT INTO card_distractors(card_id,back_hash,wrong,model,created) VALUES(?,?,CAST(? AS jsonb),?,?) "
                          "ON CONFLICT(card_id) DO UPDATE SET back_hash=EXCLUDED.back_hash, wrong=EXCLUDED.wrong, model=EXCLUDED.model, created=EXCLUDED.created",
                          (c["id"], run._distractor_hash(c["back"]), json.dumps(valid), run.CHEAP_MODEL, time.time()))
                filled += 1
    print(f"  distractors: filled {filled}")
    return filled


def fill_hints(cid, dry=False):
    """A hint for every card's quiz question (front + its cached option set), keyed exactly as /hint reads."""
    rows = run.rows("SELECT c.id, c.front, c.back, d.wrong FROM cards c "
                    "JOIN card_distractors d ON d.card_id=c.id WHERE c.course_id=?", cid)
    missing = []
    for r in rows:
        wrong = r["wrong"] if isinstance(r["wrong"], list) else json.loads(r["wrong"])
        options = list(wrong) + [r["back"]]
        key = run._hint_key(cid, r["front"], options)
        if not run.rows("SELECT 1 FROM hint_cache WHERE key=?", key):
            missing.append((r["front"], options, key))
    if dry:
        print(f"  hints: {len(missing)} missing")
        return len(missing)
    for question, options, key in missing:
        m = run.ask_model(run.CHEAP_MODEL, task="hint", max_tokens=120,
                          messages=[{"role": "user", "content": run._hint_prompt(question, options)}])
        text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip()[:300]
        with run.db() as d:
            d.execute("INSERT INTO hint_cache(key,course_id,hint,model,created) VALUES(?,?,?,?,?) "
                      "ON CONFLICT(key) DO UPDATE SET hint=EXCLUDED.hint, model=EXCLUDED.model, created=EXCLUDED.created",
                      (key, cid, text, run.CHEAP_MODEL, time.time()))
    print(f"  hints: filled {len(missing)}")
    return len(missing)


_ITALIC_CASE = re.compile(r"\*([A-Z][A-Za-z.\- ]{3,60})\*")   # *Dassonville*, *Cassis de Dijon*


def _case_names(cid, explicit):
    if explicit:
        return explicit
    seen = {}
    for n in run.rows("SELECT body FROM notes WHERE course_id=?", cid):
        for m in _ITALIC_CASE.finditer(n["body"] or ""):
            name = m.group(1).strip()
            seen[name.casefold()] = name
    return list(seen.values())


def fill_court(cid, cases, dry=False):
    """Build and cache a hearing for each case the notes discuss, keyed exactly as /court reads."""
    names = _case_names(cid, cases)
    built = 0
    for name in names:
        context = run._case_context(cid, name)
        if not context.strip():
            continue
        key = run._court_key(cid, name, context)
        if run.rows("SELECT 1 FROM court_cache WHERE key=?", key):
            continue
        if dry:
            print(f"  court: '{name}' missing")
            built += 1
            continue
        m = run.ask_model(run.CHEAP_MODEL, task="court", max_tokens=1400,
                          messages=[{"role": "user", "content": run._court_prompt(name, context)}])
        try:
            hearing = run._court_shape(run._model_json(m), name)
        except Exception as e:
            print(f"  court: '{name}' skipped ({type(e).__name__})")
            continue
        with run.db() as d:
            d.execute("INSERT INTO court_cache(key,course_id,hearing,model,created) VALUES(?,?,CAST(? AS jsonb),?,?) "
                      "ON CONFLICT(key) DO UPDATE SET hearing=EXCLUDED.hearing, model=EXCLUDED.model, created=EXCLUDED.created",
                      (key, cid, json.dumps(hearing), run.CHEAP_MODEL, time.time()))
        built += 1
    if not dry:
        print(f"  court: built {built}")
    return built


def calibrate(cid, cases):
    """Print the local grader's score spread over synthetic anchors from the notes — no labelled data
    needed (Gemini's threshold-without-labels idea): a perturbed reference ≈ 'solid', an unrelated
    sentence ≈ 'missed'. Use the spread to sanity-check courtgrade.SOLID / courtgrade.SHAKY."""
    import courtgrade as cg
    for name in _case_names(cid, cases):
        context = run._case_context(cid, name)
        sents = cg.sentences(context)
        if len(sents) < 2:
            continue
        print(f"\n[{name}]  ({len(sents)} note sentences)")
        q = f"What did the court decide in {name}?"
        anchors = [("ref-verbatim (≈solid)", sents[0]),
                   ("ref-dropword (≈solid)", " ".join(sents[0].split()[::2])),
                   ("other-sentence (≈shaky)", sents[-1]),
                   ("off-topic (≈missed)", "Something unrelated about administrative procedure.")]
        for label, ans in anchors:
            g = cg.grade(q, ans, context)
            print(f"    {g['mastery']:7s}  {label}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--course", help="course id; default every course")
    ap.add_argument("--case", action="append", default=[], help="specific case name for a hearing (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="report what is missing; generate nothing")
    ap.add_argument("--calibrate", action="store_true", help="print grader score spread; fill nothing")
    a = ap.parse_args()
    for cid in _courses(a.course):
        print(f"course {cid}:")
        if a.calibrate:
            calibrate(cid, a.case)
            continue
        fill_distractors(cid, a.dry_run)
        fill_hints(cid, a.dry_run)
        fill_court(cid, a.case, a.dry_run)


if __name__ == "__main__":
    main()
