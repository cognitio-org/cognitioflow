"""Tests: scripts/cutover.sh rehearsed locally — a fixture laptop folder into the test database and test storage."""
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import storage
from test_migrate_sqlite import _make_fixture_db

ROOT = Path(__file__).resolve().parent.parent
REHEARSAL = ("--local", "--allow-running")  # the live laptop app may be on :8000 while tests run


def _laptop(tmp_path):
    """A laptop-build folder: data/cognitioflow.db plus the uploads/audio its rows point at (absolute laptop paths)."""
    data = tmp_path / "laptop" / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "audio").mkdir()
    db = data / "cognitioflow.db"
    _make_fixture_db(str(db))
    conn = sqlite3.connect(db)
    fid = conn.execute("SELECT id FROM files").fetchone()[0]
    nid = conn.execute("SELECT id FROM notes").fetchone()[0]
    conn.execute("UPDATE files SET path=?", (f"/Users/m/Desktop/cognitioflow/data/uploads/{fid}_file.txt",))
    conn.execute("INSERT INTO recordings VALUES(?,?,?,?,?)", ("rec1", nid, "/Users/m/Desktop/cognitioflow/data/audio/rec1.webm", time.time(), 5.0))
    conn.commit()
    conn.close()
    (data / "uploads" / f"{fid}_file.txt").write_bytes(b"content")
    (data / "audio" / "rec1.webm").write_bytes(b"webm-audio")
    return tmp_path / "laptop", fid, nid


def _run(*args, answers=""):
    return subprocess.run(["bash", "scripts/cutover.sh", *args], cwd=ROOT, input=answers, capture_output=True, text=True,
                          env={**os.environ, "MATEJ_EMAIL": "test@example.com"})


def test_dry_run_reports_counts_and_writes_nothing(tmp_path, pg):
    laptop, _, _ = _laptop(tmp_path)
    r = _run("--from", str(laptop), *REHEARSAL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY RUN" in r.stdout and "Dry run complete" in r.stdout
    assert "2 stored file(s) referenced by the database, 0 missing" in r.stdout
    assert pg.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_dry_run_fails_when_a_referenced_file_is_missing(tmp_path):
    laptop, _, _ = _laptop(tmp_path)
    (laptop / "data" / "audio" / "rec1.webm").unlink()
    r = _run("--from", str(laptop), *REHEARSAL)
    assert r.returncode == 1
    assert "audio/rec1.webm is referenced but not in the data folder" in r.stdout


def test_execute_stops_when_you_answer_no(tmp_path, pg):
    laptop, _, _ = _laptop(tmp_path)
    r = _run("--from", str(laptop), "--workdir", str(tmp_path / "work"), "--execute", *REHEARSAL, answers="n\n")
    assert r.returncode == 1 and "stopped by you" in r.stderr
    assert not (tmp_path / "work").exists()
    assert pg.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_execute_rehearsal_moves_rows_and_files(tmp_path, pg):
    laptop, fid, nid = _laptop(tmp_path)
    r = _run("--from", str(laptop), "--workdir", str(tmp_path / "work"), "--execute", "--yes", *REHEARSAL)
    assert r.returncode == 0, r.stdout + r.stderr
    for expected in ("snapshot taken", "Verified — counts match and sampled rows are identical.", "OK — every row accounted for.", "Cutover complete"):
        assert expected in r.stdout, expected
    assert (tmp_path / "work" / "cognitioflow.db").exists()
    keys = dict(pg.execute("SELECT id, key FROM files UNION ALL SELECT id, key FROM recordings").fetchall())
    assert keys["rec1"] == f"notes/{nid}/audio/rec1.webm"
    assert keys[fid].endswith(f"/files/{fid}/file.txt")
    assert storage.get(keys["rec1"]) == b"webm-audio" and storage.get(keys[fid]) == b"content"
    assert pg.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
