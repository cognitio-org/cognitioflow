"""The courtroom: a missed bench question has to come back, and must not pile up.

Until now the grader wrote the gap and its authority, the page rendered the verdict, and the note was
dropped — so the courtroom could tell you that you were wrong but never help you stop being wrong.
"""
import json
from datetime import date
from unittest import mock

import run


def _bench(payload):
    msg = mock.MagicMock()
    msg.content = [mock.MagicMock(type="text", text=json.dumps(payload))]
    fake = mock.MagicMock()
    fake.messages.create.return_value = msg
    return fake


MISSED = {"mastery": "missed", "verdict": "Not yet", "spoken": "You did not reach the justification.",
          "note": "forgot the proportionality limb — Cassis"}
SOLID = {"mastery": "solid", "verdict": "Solid", "spoken": "That is right.", "note": ""}

CASE = "Dassonville"
QUESTION = "What must the measure be capable of doing to fall within Article 34?"


def _course(pg):
    cid = pg.execute("SELECT id FROM courses ORDER BY created LIMIT 1").fetchone()[0]
    pg.execute("INSERT INTO notes(id,course_id,title,body,updated) VALUES(%s,%s,%s,%s,%s)",
               ("n-court", cid, "Week 3", f"*{CASE}* — all trading rules capable of hindering trade.", 0))
    pg.commit()
    return cid


def _reply(client, cid, payload, answer="Something vague."):
    with mock.patch.object(run, "client", return_value=_bench(payload)):
        return client.post(f"/api/courses/{cid}/court/reply",
                           json={"case": CASE, "question": QUESTION, "answer": answer})


def test_a_missed_bench_question_becomes_a_card_due_today(client, pg):
    cid = _course(pg)
    r = _reply(client, cid, MISSED)
    assert r.status_code == 200 and r.json()["mastery"] == "missed"

    card = pg.execute("SELECT front,back,source,concept,due FROM cards WHERE course_id=%s AND source LIKE 'court:%%'",
                      (cid,)).fetchone()
    assert card is not None, "a missed bench question must leave a card behind"
    front, back, source, concept, due = card
    assert front == QUESTION
    assert back == MISSED["note"], "the card carries the gap and its authority, which is the whole point"
    assert source == f"court:{CASE}" and concept == CASE
    assert due == date.today().isoformat(), "it goes into the queue now, not eventually"


def test_the_reply_tells_the_page_when_the_card_is_due(client, pg):
    cid = _course(pg)
    assert _reply(client, cid, MISSED).json()["due"] == date.today().isoformat()


def test_a_solid_answer_leaves_no_card(client, pg):
    cid = _course(pg)
    r = _reply(client, cid, SOLID, answer="Capable of hindering trade, directly or indirectly.")
    assert r.status_code == 200 and r.json()["mastery"] == "solid"
    assert "due" not in r.json()
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE course_id=%s", (cid,)).fetchone()[0] == 0


def test_the_same_question_missed_twice_leaves_one_card(client, pg):
    """Ten hearings on one case must leave one card per question, not ten."""
    cid = _course(pg)
    _reply(client, cid, MISSED)
    _reply(client, cid, MISSED)
    n = pg.execute("SELECT COUNT(*) FROM cards WHERE course_id=%s AND source LIKE 'court:%%'", (cid,)).fetchone()[0]
    assert n == 1, f"expected one card for one question, found {n}"


def test_missing_it_again_is_rated_through_the_apps_own_review_path(client, pg):
    """Recurrence is decided in exactly one place; the courtroom must not invent a second."""
    cid = _course(pg)
    _reply(client, cid, MISSED)
    with mock.patch.object(run, "review", wraps=run.review) as review:
        _reply(client, cid, MISSED)
    assert review.call_count == 1, "the second miss goes through review(), not a fresh insert"
    assert review.call_args.args[1].rating == 0, "a miss is rated 'again'"


def test_two_different_questions_on_one_case_keep_their_own_cards(client, pg):
    cid = _course(pg)
    _reply(client, cid, MISSED)
    with mock.patch.object(run, "client", return_value=_bench(MISSED)):
        client.post(f"/api/courses/{cid}/court/reply",
                    json={"case": CASE, "question": "And what is the effect on inter-State trade?", "answer": "?"})
    n = pg.execute("SELECT COUNT(*) FROM cards WHERE course_id=%s AND source LIKE 'court:%%'", (cid,)).fetchone()[0]
    assert n == 2


def test_a_bench_that_does_not_answer_is_still_a_502(client, pg):
    """The persistence sits outside the try; the model's own failure must still read as one."""
    cid = _course(pg)
    broken = mock.MagicMock()
    broken.messages.create.side_effect = RuntimeError("upstream is down")
    with mock.patch.object(run, "client", return_value=broken):
        r = client.post(f"/api/courses/{cid}/court/reply",
                        json={"case": CASE, "question": QUESTION, "answer": "x"})
    assert r.status_code == 502
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE course_id=%s", (cid,)).fetchone()[0] == 0


# ---------------------------------------------------------------- the page half of the same gap
#
# The server writes the card and returns its due date; until now the page threw that away, so a
# hearing still ended with no sign that anything had been kept. There is no JS test runner here and
# CLAUDE.md forbids adding one, so these assert against the page source the way test_courses.py's
# palette test does — plus one behavioural check of dueWord through node when node is present.
import re
import shutil
import subprocess
from pathlib import Path

# index.html was split on 2026-09-18: JS to static/app.js, CSS to static/app.css
# and static/book.css. These assertions are about the shipped UI, so read all of it.
def _page_text():
    d = Path(__file__).resolve().parent.parent / "static"
    out = []
    for n in ("index.html", "app.js", "app.css", "book.css"):
        f = d / n
        if f.exists():
            out.append(f.read_text(encoding="utf-8"))
    return chr(10).join(out)


import pytest

PAGE = _page_text()


def test_the_page_consumes_the_due_date_the_bench_returns():
    """The regression itself: court_reply returns `due` and the reply handler has to act on it."""
    handler = re.search(r"async function courtReply\(text\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "g.due" in handler, "courtReply ignores the due date, so a kept card is invisible again"
    assert "court.kept++" in handler


def test_the_tally_resets_with_each_hearing():
    """kept counts one hearing. Left running, the second hearing on a case inherits the first's total."""
    opener = re.search(r"async function openCase\(name\)\{.*?\n\}", PAGE, re.S).group(0)
    assert "court.kept=0" in opener.replace(" ", "")


def test_the_close_of_the_hearing_points_at_recall():
    """Naming where the cards went is the whole point; #recall is reached through the existing nav hook."""
    ask = re.search(r"function benchAsk\(\)\{.*?\n\}", PAGE, re.S).group(0)
    assert 'data-nav="recall"' in ask


@pytest.mark.skipif(not shutil.which("node"), reason="node is not on this machine")
def test_due_word_says_what_the_rest_of_the_app_says():
    """today / tomorrow / a date, and nothing at all for a value the server never sends."""
    fn = re.search(r"\nfunction dueWord\(iso\)\{.*?\n\}\n", PAGE, re.S).group(0)
    script = fn + """
const at=d=>{const x=new Date();x.setHours(0,0,0,0);x.setDate(x.getDate()+d);
  return `${x.getFullYear()}-${String(x.getMonth()+1).padStart(2,'0')}-${String(x.getDate()).padStart(2,'0')}`};
console.log(JSON.stringify([dueWord(at(0)),dueWord(at(1)),dueWord(at(9)),dueWord(at(-3)),dueWord(''),dueWord('nonsense')]));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    today, tomorrow, later, overdue, empty, junk = json.loads(out.stdout)
    assert today == "due today"
    assert tomorrow == "due tomorrow"
    assert re.fullmatch(r"due \d{1,2} \w+", later), later
    assert overdue == "due today", "an overdue card is due now, not 'due -3 days'"
    assert empty == "" and junk == "", "a missing or unreadable date must render nothing, not 'Invalid Date'"
