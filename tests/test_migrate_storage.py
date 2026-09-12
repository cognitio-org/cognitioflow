"""Tests: migrate_storage.py — legacy laptop paths → storage keys."""
import os
import subprocess
import sys
import time

import migrate_storage
import storage

ROOT = os.path.dirname(os.path.dirname(__file__))


def _legacy(tmp_path, pg):
    """An old-build data/ folder plus rows whose keys are still absolute laptop paths (as migrate_sqlite leaves them)."""
    data = tmp_path / "data"
    for key in ("courses/eu/files/f1/Week 1 slides.pdf", "notes/n1/audio/r1.webm"):
        storage.delete(key)  # the fake-gcs bucket outlives a test session
    (data / "uploads").mkdir(parents=True); (data / "audio").mkdir()
    (data / "uploads" / "f1_Week 1 slides.pdf").write_bytes(b"%PDF-week1")
    (data / "audio" / "r1.webm").write_bytes(b"webm-audio")
    old = "/Users/matej/Desktop/cognitioflow/data"
    pg.execute("INSERT INTO files(id,course_id,name,kind,key,text,chars,selected,status,week,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
               ("f1", "eu", "Week 1 slides.pdf", "pdf", f"{old}/uploads/f1_Week 1 slides.pdf", "Art 34", 6, 1, "indexed", "1", time.time()))
    pg.execute("INSERT INTO recordings(id,note_id,key,started,seconds) VALUES(%s,%s,%s,%s,%s)", ("r1", "n1", f"{old}/audio/r1.webm", time.time(), 5))
    pg.execute("INSERT INTO recordings(id,note_id,key,started,seconds) VALUES(%s,%s,%s,%s,%s)", ("r2", "n1", "", time.time(), 0))
    pg.commit()
    return data


def _keys(pg):
    return dict(pg.execute("SELECT id, key FROM files UNION ALL SELECT id, key FROM recordings").fetchall())


def test_dry_run_counts_and_writes_nothing(tmp_path, pg):
    data = _legacy(tmp_path, pg)
    before, lines = _keys(pg), []
    assert migrate_storage.migrate(str(data), dry_run=True, out=lines.append) == 0
    assert _keys(pg) == before
    assert not storage.exists("courses/eu/files/f1/Week 1 slides.pdf")
    assert any("files" in l and "rows=    1" in l and "to move=    1" in l for l in lines)
    assert any("recordings" in l and "rows=    2" in l and "no-audio=1" in l for l in lines)


def test_migrate_moves_bytes_rewrites_keys_and_is_idempotent(tmp_path, pg):
    data = _legacy(tmp_path, pg)
    assert migrate_storage.migrate(str(data), out=lambda _: None) == 0
    keys = _keys(pg)
    assert keys["f1"] == "courses/eu/files/f1/Week 1 slides.pdf"
    assert keys["r1"] == "notes/n1/audio/r1.webm"
    assert keys["r2"] == ""
    assert storage.get(keys["f1"]) == b"%PDF-week1"
    assert storage.get(keys["r1"]) == b"webm-audio"

    lines = []
    assert migrate_storage.migrate(str(data), out=lines.append) == 0  # second run: nothing left to move
    assert any("files" in l and "moved=    0" in l and "already=    1" in l for l in lines)
    assert migrate_storage.migrate(None, verify=True, out=lambda _: None) == 0


def test_missing_source_file_fails_the_count(tmp_path, pg):
    data = _legacy(tmp_path, pg)
    (data / "uploads" / "f1_Week 1 slides.pdf").unlink()
    lines = []
    assert migrate_storage.migrate(str(data), dry_run=True, out=lines.append) == 1
    assert any("✗ files f1" in l for l in lines)


def test_verify_flags_unmigrated_rows(tmp_path, pg):
    _legacy(tmp_path, pg)
    assert migrate_storage.migrate(None, verify=True, out=lambda _: None) == 2


def test_cli_exits_non_zero_on_mismatch(tmp_path, pg):
    data = _legacy(tmp_path, pg)
    (data / "audio" / "r1.webm").unlink()
    env = {**os.environ, "STORAGE": os.environ.get("STORAGE", "local")}
    r = subprocess.run([sys.executable, "migrate_storage.py", "--data", str(data), "--dry-run"], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "MISMATCH" in r.stdout
