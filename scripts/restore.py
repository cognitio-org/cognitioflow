#!/usr/bin/env python3
"""
Restore a backup made by scripts/backup.py.

  python3 scripts/restore.py --list
  python3 scripts/restore.py --latest --database-url "$TARGET"                          # into an empty database
  python3 scripts/restore.py --stamp 2026-09-20T0100Z --database-url "$TARGET" --objects-to ~/cf-restore/files
  python3 scripts/restore.py --latest --database-url "$TARGET" --objects-to gs://another-bucket

Target: --database-url, else RESTORE_DATABASE_URL. DATABASE_URL is deliberately never read, so production is never
the default target. A target that already holds rows is refused unless --replace.
Checks: the dump's sha256 against the manifest before restoring; every table's row count after.
--objects-to copies the stored files back, into a local folder (through storage.LocalStorage) or a bucket.
Environment: BACKUP_BUCKET (default cognitioflow-backups), GCP_PROJECT, STORAGE_EMULATOR_HOST for fake-gcs.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import backup as backup_mod  # noqa: E402
import pgtools  # noqa: E402
import storage  # noqa: E402


def _describe(url: str) -> str:
    p = urlsplit(url)
    return f"{p.hostname}/{p.path.lstrip('/')}"


def _server_major(url: str) -> int:
    with psycopg.connect(url) as conn:
        return pgtools.major(conn.execute("SHOW server_version").fetchone()[0])


def _rows(url: str) -> dict:
    with psycopg.connect(url) as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def restore(stamp: str, database_url: str, backup_bucket: str, cl=None, replace=False, objects_to=None, log=print) -> dict:
    cl = cl or backup_mod.client()
    bucket = cl.bucket(backup_bucket)
    manifest = json.loads(bucket.blob(f"{stamp}/{backup_mod.MANIFEST}").download_as_bytes())
    existing = _rows(database_url)
    if sum(existing.values()) and not replace:
        busy = ", ".join(f"{t} {n}" for t, n in existing.items() if n)
        raise RuntimeError(f"{_describe(database_url)} already holds data ({busy}); pass --replace to overwrite it")

    with tempfile.TemporaryDirectory(prefix="cf-restore-") as work:
        dump = Path(work) / "db.dump"
        bucket.blob(manifest["database"]["dump"]["key"]).download_to_filename(str(dump))
        if backup_mod.sha256(dump) != manifest["database"]["dump"]["sha256"]:
            raise RuntimeError("downloaded dump does not match the manifest's sha256; not restoring it")
        dump_major = manifest["database"]["pg_dump_major"]
        options = ["--no-owner", "--no-privileges", "--clean", "--if-exists"]
        if _server_major(database_url) >= dump_major:
            pgtools.run("pg_restore", dump_major, [*options, "--exit-on-error", "{work}/db.dump"], database_url, work)
        else:
            # An older target (e.g. a local Postgres 16 for a drill): newer pg_restore emits settings that server rejects,
            # so render the dump as SQL, drop those lines, and apply it in one transaction that stops at the first error.
            pgtools.run("pg_restore", dump_major, [*options, "--file={work}/restore.sql", "{work}/db.dump"], database_url, work, connect=False)
            sql = Path(work) / "restore.sql"
            sql.write_text("".join(line for line in sql.read_text().splitlines(keepends=True)
                                   if not line.startswith("SET transaction_timeout")))
            pgtools.run("psql", 0, ["--quiet", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "--single-transaction",
                                    "--file={work}/restore.sql"], database_url, work)
    got = _rows(database_url)
    mismatched = {t: {"backup": n, "restored": got.get(t)} for t, n in manifest["database"]["tables"].items() if got.get(t) != n}
    log(f"database: restored into {_describe(database_url)}, {len(manifest['database']['tables'])} tables, "
        f"{len(mismatched)} with a different row count")

    report = {"stamp": stamp, "tables_mismatched": mismatched, "objects": None}
    if objects_to:
        prefix = manifest["objects"]["prefix"]
        count = size = 0
        if str(objects_to).startswith("gs://"):
            dst = cl.bucket(str(objects_to)[5:].strip("/"))
            for blob in cl.list_blobs(backup_bucket, prefix=prefix):
                target = dst.blob(blob.name[len(prefix):])
                token = None
                while True:
                    token, _, _ = target.rewrite(blob, token=token, **({} if replace else {"if_generation_match": 0}))
                    if token is None:
                        break
                count += 1
                size += blob.size or 0
        else:
            local = storage.LocalStorage(Path(objects_to).expanduser())
            for blob in cl.list_blobs(backup_bucket, prefix=prefix):
                data = blob.download_as_bytes()
                local.put(blob.name[len(prefix):], data)
                count += 1
                size += len(data)
        ok = count == manifest["objects"]["count"] and size == manifest["objects"]["bytes"]
        report["objects"] = {"to": str(objects_to), "count": count, "bytes": size, "matches_manifest": ok}
        log(f"objects: {count} restored to {objects_to} ({size / 1e6:.1f} MB), {'matches' if ok else 'DOES NOT match'} the manifest")
    return report


def main():
    ap = argparse.ArgumentParser(description="Restore a CognitioFlow backup")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--latest", action="store_true", help="the newest completed backup")
    which.add_argument("--stamp", help="a backup stamp, e.g. 2026-09-20T0100Z")
    which.add_argument("--list", action="store_true", help="list completed backups")
    ap.add_argument("--database-url", default=os.environ.get("RESTORE_DATABASE_URL"), help="target database (never defaults to DATABASE_URL)")
    ap.add_argument("--objects-to", help="local folder or gs://bucket to copy the stored files into")
    ap.add_argument("--replace", action="store_true", help="allow a target database or bucket that already holds data")
    a = ap.parse_args()
    bucket = os.environ.get("BACKUP_BUCKET", "cognitioflow-backups")
    cl = backup_mod.client()
    backups = backup_mod.list_backups(cl, bucket)
    if a.list or not (a.latest or a.stamp):
        for m in backups:
            print(f"{m['stamp']}  {sum(m['database']['tables'].values()):>6} rows  {m['objects']['count']:>4} objects")
        return 0
    if not a.database_url:
        print("give --database-url (or RESTORE_DATABASE_URL); DATABASE_URL is never used as a restore target", file=sys.stderr)
        return 1
    if not backups:
        print(f"no completed backups in gs://{bucket}", file=sys.stderr)
        return 1
    stamp = backups[0]["stamp"] if a.latest else a.stamp
    try:
        report = restore(stamp, a.database_url, bucket, cl=cl, replace=a.replace, objects_to=a.objects_to)
    except (RuntimeError, psycopg.Error) as e:
        print(f"RESTORE FAILED: {e}", file=sys.stderr)
        return 1
    bad = report["tables_mismatched"] or (report["objects"] and not report["objects"]["matches_manifest"])
    print("RESTORE OK" if not bad else "RESTORE FINISHED WITH MISMATCHES", json.dumps(report, indent=1) if bad else "")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
