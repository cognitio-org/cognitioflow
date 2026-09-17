"""
Tests: the local development fixture (scripts/seed_dev.py).

Two things have to hold. It must run and be idempotent, so `make seed` is safe to repeat. And it
must refuse to run anywhere that is not a local database — CLAUDE.md forbids fabricated user
content on a Neon branch, and a seed script pointed at the wrong DATABASE_URL is how that happens.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("seed_dev", ROOT / "scripts" / "seed_dev.py")
seed_dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_dev)

COUNTS = "SELECT (SELECT COUNT(*) FROM notes), (SELECT COUNT(*) FROM cards), (SELECT COUNT(*) FROM sessions), (SELECT COUNT(*) FROM files)"


@pytest.mark.parametrize("url, reason", [
    ("postgresql://u:p@ep-cool-123.eu-central-1.aws.neon.tech/cognitioflow?sslmode=require", "neon.tech"),
    ("postgresql://u:p@db.abcdefgh.supabase.co:5432/postgres", "supabase."),
    ("postgresql://u:p@10.20.30.40:5432/cognitioflow", "not a local host"),
    ("postgresql://u:p@cognitioflow.example.com/cognitioflow", "not a local host"),
])
def test_a_database_that_is_not_local_is_refused(url, reason):
    with pytest.raises(seed_dev.NotLocal) as e:
        seed_dev.assert_local(url)
    assert reason in str(e.value)
    assert "p@" not in str(e.value), "the refusal must not echo the URL — it carries a password"


@pytest.mark.parametrize("url", [
    "postgresql://cf:cf@localhost:5432/cognitioflow",
    "postgresql://cf:cf@127.0.0.1:5432/cognitioflow",
    "postgresql://cf:cf@db:5432/cognitioflow",          # the docker compose service name
])
def test_a_local_database_is_allowed(url):
    assert seed_dev.assert_local(url)


def test_production_is_refused_even_on_a_local_url(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(seed_dev.NotLocal) as e:
        seed_dev.assert_local("postgresql://cf:cf@localhost:5432/cognitioflow")
    assert "production" in str(e.value)


def test_the_seed_runs_and_is_idempotent(client, pg):
    """Twice must leave exactly what once left, or `make seed` is not safe to repeat."""
    seed_dev.seed(quiet=True)
    first = pg.execute(COUNTS).fetchone()
    assert all(n > 0 for n in first), f"the seed wrote nothing: {first}"

    seed_dev.seed(quiet=True)
    assert pg.execute(COUNTS).fetchone() == first


def test_the_seed_fills_every_screen_that_was_empty(client, pg):
    seed_dev.seed(quiet=True)

    notes = pg.execute("SELECT title, body FROM notes WHERE id LIKE 'fix-%'").fetchall()
    assert len(notes) >= 8, "the note rail needs enough notes to scroll"
    assert max(len(b) for _, b in notes) > 15_000, "one note must be long enough to judge the reading column"
    everything = "\n".join(b for _, b in notes)
    for element in ("```mermaid", "| --- |", "> **", "●●", "*Dassonville*", "### "):
        assert element in everything, f"no note exercises {element!r}"
    for tag in ("[LECTURE]", "[WG]", "[SLIDES]", "[READER]", "[SCHUTZE]"):
        assert tag in everything, f"provenance tag {tag} is never rendered"

    # Recall can only be judged if every queue state is reachable.
    due, overdue, ahead, new = pg.execute(
        "SELECT COUNT(*) FILTER (WHERE due = CURRENT_DATE::text),"
        "       COUNT(*) FILTER (WHERE due < CURRENT_DATE::text),"
        "       COUNT(*) FILTER (WHERE due > CURRENT_DATE::text),"
        "       COUNT(*) FILTER (WHERE state IS NULL)"
        " FROM cards WHERE id LIKE 'fix-%'").fetchone()
    assert due and overdue and ahead and new, f"queue states missing: {(due, overdue, ahead, new)}"
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE id LIKE 'fix-%' AND ease < 2.3").fetchone()[0], "no weak cards"

    past, future = pg.execute(
        "SELECT COUNT(*) FILTER (WHERE day < CURRENT_DATE::text), COUNT(*) FILTER (WHERE day > CURRENT_DATE::text)"
        " FROM sessions WHERE id LIKE 'fix-%'").fetchone()
    assert past and future, "the planner needs sessions on both sides of today"

    ticked, unticked = pg.execute(
        "SELECT COUNT(*) FILTER (WHERE selected = 1), COUNT(*) FILTER (WHERE selected = 0)"
        " FROM files WHERE id LIKE 'fix-%'").fetchone()
    assert ticked and unticked, "Files needs both ticked and unticked rows"

    for course in ("eu", "prop"):
        # the literal % needs doubling once the query also carries a placeholder
        assert pg.execute("SELECT COUNT(*) FROM notes WHERE id LIKE 'fix-%%' AND course_id=%s",
                          (course,)).fetchone()[0], f"{course} has no fixture notes"


def test_clear_removes_the_fixture_and_leaves_real_rows(client, pg):
    seed_dev.seed(quiet=True)
    pg.execute("INSERT INTO notes(id,course_id,title,body,updated) VALUES('mine','eu','Mine','Written by hand',1)")
    pg.commit()

    seed_dev.clear(quiet=True)
    assert pg.execute("SELECT COUNT(*) FROM notes WHERE id LIKE 'fix-%'").fetchone()[0] == 0
    assert pg.execute("SELECT COUNT(*) FROM cards WHERE id LIKE 'fix-%'").fetchone()[0] == 0
    assert pg.execute("SELECT title FROM notes WHERE id='mine'").fetchone()[0] == "Mine"
