"""Test migrate_sqlite.py --dry-run against a small fixture database."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

import pytest


def _make_fixture_db(path: str) -> dict[str, int]:
    """Create a minimal SQLite fixture and return expected row counts per table."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE courses(id TEXT PRIMARY KEY, name TEXT, accent TEXT,
            tutor_prompt TEXT DEFAULT '', created REAL);
        CREATE TABLE files(id TEXT PRIMARY KEY, course_id TEXT, name TEXT, kind TEXT,
            path TEXT, text TEXT, chars INTEGER, selected INTEGER DEFAULT 1,
            status TEXT, week TEXT DEFAULT '', created REAL);
        CREATE TABLE messages(id TEXT PRIMARY KEY, course_id TEXT, role TEXT,
            content TEXT, created REAL);
        CREATE TABLE notes(id TEXT PRIMARY KEY, course_id TEXT, title TEXT,
            body TEXT, updated REAL);
        CREATE TABLE cards(id TEXT PRIMARY KEY, course_id TEXT, front TEXT, back TEXT,
            source TEXT DEFAULT '', ease REAL DEFAULT 2.5, interval INTEGER DEFAULT 0,
            reps INTEGER DEFAULT 0, due TEXT, created REAL);
        CREATE TABLE reviews(id TEXT PRIMARY KEY, card_id TEXT, rating INTEGER,
            created REAL);
        CREATE TABLE note_versions(id TEXT PRIMARY KEY, note_id TEXT, title TEXT,
            body TEXT, created REAL);
        CREATE TABLE recordings(id TEXT PRIMARY KEY, note_id TEXT, path TEXT,
            started REAL, seconds REAL DEFAULT 0);
        CREATE TABLE sessions(id TEXT PRIMARY KEY, course_id TEXT, day TEXT,
            topic TEXT, minutes INTEGER, done INTEGER DEFAULT 0);
    """)

    now = time.time()
    cid = uuid.uuid4().hex[:8]
    nid = uuid.uuid4().hex[:10]
    kid = uuid.uuid4().hex[:10]

    conn.execute("INSERT INTO courses VALUES(?,?,?,?,?)",
                 (cid, "Test Course", "#000", "", now))
    conn.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (uuid.uuid4().hex, cid, "file.txt", "text", "/tmp/x.txt",
                  "content", 7, 1, "indexed", "1", now))
    conn.execute("INSERT INTO notes VALUES(?,?,?,?,?)",
                 (nid, cid, "Note", "body", now))
    conn.execute("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (kid, cid, "Q", "A", "", 2.5, 0, 0, "2026-09-12", now))
    conn.execute("INSERT INTO reviews VALUES(?,?,?,?)",
                 (uuid.uuid4().hex, kid, 2, now))
    conn.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                 (uuid.uuid4().hex, cid, "2026-09-12", "Study", 45, 0))
    conn.commit()
    conn.close()

    return {
        "courses": 1, "files": 1, "messages": 0, "notes": 1,
        "cards": 1, "reviews": 1, "note_versions": 0, "recordings": 0, "sessions": 1,
    }


def test_migrate_sqlite_dry_run_reports_counts():
    """--dry-run must exit 0 and print the correct source counts for all 9 tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    expected = _make_fixture_db(db_path)

    env = os.environ.copy()
    env.setdefault("DATABASE_URL", "postgresql://cf:cf@localhost:5432/cognitioflow")
    env.setdefault("MATEJ_EMAIL", "test@example.com")

    result = subprocess.run(
        [sys.executable, "migrate_sqlite.py", "--sqlite", db_path, "--dry-run"],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )

    assert result.returncode == 0, f"Non-zero exit:\n{result.stdout}\n{result.stderr}"

    output = result.stdout
    for table, count in expected.items():
        assert table in output, f"Table '{table}' not in output"
        assert str(count) in output, f"Count {count} for '{table}' not in output"

    os.unlink(db_path)


def test_migrate_sqlite_maps_path_to_key(pg):
    """Phase 2 renamed path → key; the laptop path is carried over for migrate_storage.py to move."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _make_fixture_db(db_path)
    env = {**os.environ, "MATEJ_EMAIL": "test@example.com"}
    result = subprocess.run(
        [sys.executable, "migrate_sqlite.py", "--sqlite", db_path],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    os.unlink(db_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert pg.execute("SELECT key FROM files").fetchall() == [("/tmp/x.txt",)]


def _cli(*args):
    return subprocess.run([sys.executable, "migrate_sqlite.py", *args], capture_output=True, text=True,
                          env={**os.environ, "MATEJ_EMAIL": "test@example.com"}, cwd=os.path.dirname(os.path.dirname(__file__)))


def _fixture_with_recording():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _make_fixture_db(db_path)
    conn = sqlite3.connect(db_path)
    nid = conn.execute("SELECT id FROM notes").fetchone()[0]
    conn.execute("INSERT INTO recordings VALUES(?,?,?,?,?)", ("rec1", nid, "/Users/m/Desktop/cognitioflow/data/audio/rec1.webm", time.time(), 12.5))
    conn.commit(); conn.close()
    return db_path, nid


def test_verify_passes_after_migration_and_catches_a_changed_row(pg):
    db_path, nid = _fixture_with_recording()
    try:
        assert _cli("--sqlite", db_path).returncode == 0
        ok = _cli("--sqlite", db_path, "--verify")
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "3 random rows" in ok.stdout and "3 identical" in ok.stdout
        pg.execute("UPDATE notes SET body='tampered' WHERE id=%s", (nid,)); pg.commit()
        bad = _cli("--sqlite", db_path, "--verify")
        assert bad.returncode == 1 and f"✗ notes {nid}: body" in bad.stdout
    finally:
        os.unlink(db_path)


def test_verify_accepts_recording_keys_rewritten_by_migrate_storage(pg):
    db_path, nid = _fixture_with_recording()
    try:
        assert _cli("--sqlite", db_path).returncode == 0
        pg.execute("UPDATE recordings SET key=%s WHERE id='rec1'", (f"notes/{nid}/audio/rec1.webm",)); pg.commit()
        r = _cli("--sqlite", db_path, "--verify")
        assert r.returncode == 0, r.stdout
    finally:
        os.unlink(db_path)


def test_shell_database_url_wins_over_env_local():
    """The cutover runs `DATABASE_URL=<Neon prod> python migrate_sqlite.py …` from the repo folder."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrate_sqlite.py")).read()
    assert 'load_dotenv(".env.local", override=True)' not in src
