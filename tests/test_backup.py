"""Phase 7: scripts/backup.py and scripts/restore.py — local Postgres plus the fake-gcs emulator.

Seeding tests only run against a local database (never a Neon branch of production) with fake-gcs configured.
pg_dump/pg_restore come from the local install when new enough, otherwise from the postgres:18 image via Docker.
"""
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import backup  # noqa: E402
import pgtools  # noqa: E402
import restore  # noqa: E402
import storage  # noqa: E402

SRC, DST = "cf-test-backup-src", "cf-test-backups"
STAMP = "2026-01-04T0300Z"
QUIET = lambda *_: None  # noqa: E731


def _url() -> str:
    return os.environ["DATABASE_URL"]


def _with_db(url: str, name: str) -> str:
    p = urlsplit(url)
    return p._replace(path="/" + name).geturl()


def _local_db() -> bool:
    return urlsplit(_url()).hostname in ("localhost", "127.0.0.1")


needs_backend = pytest.mark.skipif(
    not os.environ.get("STORAGE_EMULATOR_HOST") or not _local_db(),
    reason="needs fake-gcs (STORAGE_EMULATOR_HOST) and a local test database; never seeds a Neon branch")


@pytest.fixture
def gcs():
    from google.cloud import storage as g
    cl = g.Client(project="test")
    for name in (SRC, DST):
        if not cl.bucket(name).exists():
            cl.create_bucket(name)
        for blob in cl.list_blobs(name):
            blob.delete()
    return cl


@pytest.fixture
def pgtools_ok(pg):
    need = pgtools.major(pg.execute("SHOW server_version").fetchone()[0])
    if not pgtools.available("pg_dump", need):
        pytest.skip(f"pg_dump {need}+ not installed and Docker not available")


@pytest.fixture
def scratch_db():
    name = "cf_restore_test"
    admin = _with_db(_url(), "postgres")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {name}")
    yield _with_db(_url(), name)
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


AUDIO = os.urandom(300_000)


@pytest.fixture
def seeded(pg, gcs):
    now = time.time()
    pg.execute("INSERT INTO users(id, email, name, created) VALUES('u1', 'owner@example.test', 'Owner', %s) ON CONFLICT DO NOTHING", (now,))
    pg.execute("INSERT INTO courses(id, name, accent, created, user_id) VALUES('bk', 'Backup Law', '#24467a', %s, 'u1') ON CONFLICT DO NOTHING", (now,))
    pg.execute("INSERT INTO notes(id, course_id, title, body, updated) VALUES('n1', 'bk', 'Week 2', %s, %s)",
               ("# Goods\nMandatory requirements — *Cassis de Dijon* [LECTURE]", now))
    pg.execute("INSERT INTO files(id, course_id, name, kind, key, text, chars, week, created) "
               "VALUES('f1', 'bk', 'W2 slides.txt', 'text', 'bk/f1/W2 slides.txt', 'slides', 6, '2', %s)", (now,))
    pg.execute("INSERT INTO recordings(id, note_id, key, started, seconds) VALUES('r1', 'n1', 'bk/rec/r1.webm', %s, 12)", (now,))
    pg.commit()
    gcs.bucket(SRC).blob("bk/f1/W2 slides.txt").upload_from_string(b"slides \x00\x01")
    gcs.bucket(SRC).blob("bk/rec/r1.webm").upload_from_string(AUDIO)
    return gcs


@needs_backend
def test_backup_then_restore_round_trip(seeded, pgtools_ok, scratch_db, tmp_path):
    m = backup.backup(_url(), SRC, DST, cl=seeded, stamp=STAMP, log=QUIET)
    assert m["database"]["tables"]["notes"] >= 1 and m["database"]["tables"]["recordings"] >= 1
    assert m["objects"] == {"source_bucket": SRC, "prefix": f"{STAMP}/objects/", "count": 2, "bytes": len(AUDIO) + 9}
    names = {b.name for b in seeded.list_blobs(DST)}
    assert {f"{STAMP}/db.dump", f"{STAMP}/manifest.json", f"{STAMP}/objects/bk/rec/r1.webm"} <= names
    assert [b["stamp"] for b in backup.list_backups(seeded, DST)] == [STAMP]

    report = restore.restore(STAMP, scratch_db, DST, cl=seeded, objects_to=tmp_path / "files", log=QUIET)
    assert report["tables_mismatched"] == {}
    assert report["objects"]["matches_manifest"] is True
    with psycopg.connect(scratch_db) as c:
        assert "Cassis de Dijon" in c.execute("SELECT body FROM notes WHERE id = 'n1'").fetchone()[0]
        assert c.execute("SELECT key FROM recordings WHERE id = 'r1'").fetchone()[0] == "bk/rec/r1.webm"
    assert storage.LocalStorage(tmp_path / "files").get("bk/rec/r1.webm") == AUDIO


@needs_backend
def test_backup_never_overwrites_an_existing_backup(seeded, pgtools_ok):
    backup.backup(_url(), SRC, DST, cl=seeded, stamp=STAMP, log=QUIET)
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        backup.backup(_url(), SRC, DST, cl=seeded, stamp=STAMP, log=QUIET)


@needs_backend
def test_restore_refuses_a_database_that_holds_data(seeded, pgtools_ok, scratch_db):
    backup.backup(_url(), SRC, DST, cl=seeded, stamp=STAMP, log=QUIET)
    restore.restore(STAMP, scratch_db, DST, cl=seeded, log=QUIET)
    with pytest.raises(RuntimeError, match="already holds data"):
        restore.restore(STAMP, scratch_db, DST, cl=seeded, log=QUIET)
    assert restore.restore(STAMP, scratch_db, DST, cl=seeded, replace=True, log=QUIET)["tables_mismatched"] == {}


@needs_backend
def test_restore_rejects_a_corrupted_dump(seeded, pgtools_ok, scratch_db):
    backup.backup(_url(), SRC, DST, cl=seeded, stamp=STAMP, log=QUIET)
    seeded.bucket(DST).blob(f"{STAMP}/db.dump").upload_from_string(b"not a dump")
    with pytest.raises(RuntimeError, match="sha256"):
        restore.restore(STAMP, scratch_db, DST, cl=seeded, log=QUIET)


@needs_backend
def test_restore_cli_never_targets_database_url(seeded, monkeypatch, capsys):
    seeded.bucket(DST).blob(f"{STAMP}/manifest.json").upload_from_string('{"stamp": "%s"}' % STAMP)
    monkeypatch.setenv("BACKUP_BUCKET", DST)
    monkeypatch.delenv("RESTORE_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["restore.py", "--latest"])
    assert restore.main() == 1
    assert "never used as a restore target" in capsys.readouterr().err


@needs_backend
def test_incomplete_backups_are_ignored(gcs):
    gcs.bucket(DST).blob("2026-01-01T0300Z/manifest.json").upload_from_string('{"stamp": "2026-01-01T0300Z"}')
    gcs.bucket(DST).blob("2026-01-08T0300Z/db.dump").upload_from_string(b"half-finished run, no manifest")
    assert [m["stamp"] for m in backup.list_backups(gcs, DST)] == ["2026-01-01T0300Z"]


def test_docker_url_reaches_the_host_database():
    assert pgtools._docker_url("postgresql://cf:p%40ss@localhost:5432/db?sslmode=disable") == \
        "postgresql://cf:p%40ss@host.docker.internal:5432/db?sslmode=disable"
    remote = "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/cognitioflow?sslmode=require"
    assert pgtools._docker_url(remote) == remote


def test_pgtools_errors_never_show_the_connection_string(tmp_path, monkeypatch):
    secret = "postgresql://u:hunter2@localhost:1/none"
    monkeypatch.setattr(pgtools, "command", lambda *a, **k: [sys.executable, "-c", f"import sys; sys.exit('cannot reach {secret}')"])
    with pytest.raises(RuntimeError) as e:
        pgtools.run("pg_dump", 18, [], secret, tmp_path)
    assert "hunter2" not in str(e.value) and "<database-url>" in str(e.value)
