"""Tests: migrations, seeding, schema correctness."""
import os
import psycopg
import pytest


def _pg_url() -> str:
    return os.environ["DATABASE_URL"]


EXPECTED_TABLES = {
    "users", "courses", "files", "messages", "notes",
    "cards", "reviews", "note_versions", "recordings", "sessions", "jobs",
    "schema_migrations",
}


def test_all_tables_exist(apply_migrations):
    """Every table from 001_initial.sql plus schema_migrations must exist."""
    with psycopg.connect(_pg_url()) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ).fetchall()
    existing = {r[0] for r in rows}
    assert EXPECTED_TABLES.issubset(existing)


def test_migrations_idempotent(apply_migrations):
    """Running the runner a third time must not raise or re-apply."""
    import migrate
    migrate.run(_pg_url())  # already applied twice in session fixture — must be safe


def test_init_seeds_two_courses_on_empty_db(clean_tables):
    """init() on a blank DB inserts exactly the two default courses."""
    import psycopg as _psycopg
    with _psycopg.connect(_pg_url()) as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    assert count_before == 0

    from run import init
    init()

    with _psycopg.connect(_pg_url()) as conn:
        rows = conn.execute("SELECT id FROM courses ORDER BY id").fetchall()
    assert {r[0] for r in rows} == {"eu", "prop"}


def test_init_seeds_zero_on_populated_db(clean_tables):
    """init() called a second time must not duplicate courses."""
    from run import init
    init()
    init()  # second call

    with psycopg.connect(_pg_url()) as conn:
        count = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
    assert count == 2
