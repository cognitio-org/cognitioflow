#!/usr/bin/env python3
"""
Backup of CognitioFlow: the database and every stored file, copied into the cold backup bucket.

  python3 scripts/backup.py            # take one backup now (the weekly Cloud Run job runs exactly this)
  python3 scripts/backup.py --list     # completed backups, newest first

Writes gs://$BACKUP_BUCKET/<UTC stamp>/
  db.dump         pg_dump --format=custom, taken inside the same database snapshot as the row counts
  objects/<key>   server-side copy of every object in $SOURCE_BUCKET, size and CRC32C checked
  manifest.json   written last. A folder without it is an incomplete backup and restore.py ignores it.
Nothing is ever overwritten: every write is conditional on the object not existing yet.

Environment: DATABASE_URL, SOURCE_BUCKET (default GCS_BUCKET, else cognitioflow-user-content),
BACKUP_BUCKET (default cognitioflow-backups), GCP_PROJECT, STORAGE_EMULATOR_HOST for fake-gcs.
Never prints DATABASE_URL. Exits 1 if anything fails to copy or verify.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage as gcs

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pgtools  # noqa: E402

MANIFEST = "manifest.json"


def client(project=None):
    return gcs.Client(project=project or os.environ.get("GCP_PROJECT"))


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_backups(cl, bucket: str) -> list:
    """Completed backups (those with a manifest), newest first, each as its manifest dict."""
    found = []
    for blob in cl.list_blobs(bucket):
        if blob.name.endswith("/" + MANIFEST) and blob.name.count("/") == 1:
            found.append(json.loads(blob.download_as_bytes()))
    return sorted(found, key=lambda m: m["stamp"], reverse=True)


def _copy_objects(cl, source_bucket: str, backup_bucket: str, prefix: str, log):
    dst = cl.bucket(backup_bucket)
    count = size = 0
    problems = []
    for blob in cl.list_blobs(source_bucket):
        target = dst.blob(prefix + "objects/" + blob.name)
        token = None
        while True:  # rewrite is server-side; large objects take several calls
            token, _, _ = target.rewrite(blob, token=token, if_generation_match=0)
            if token is None:
                break
        target.reload()
        if target.size != blob.size or (blob.crc32c and target.crc32c and target.crc32c != blob.crc32c):
            problems.append(blob.name)
        count += 1
        size += blob.size or 0
    log(f"objects: {count} copied from gs://{source_bucket} ({size / 1e6:.1f} MB), {len(problems)} mismatched")
    return count, size, problems


def backup(database_url: str, source_bucket: str, backup_bucket: str, cl=None, stamp=None, log=print) -> dict:
    cl = cl or client()
    stamp = stamp or time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    prefix = f"{stamp}/"
    if any(True for _ in cl.list_blobs(backup_bucket, prefix=prefix, max_results=1)):
        raise RuntimeError(f"gs://{backup_bucket}/{prefix} already exists; refusing to overwrite a backup")
    bucket = cl.bucket(backup_bucket)

    with tempfile.TemporaryDirectory(prefix="cf-backup-") as work, psycopg.connect(database_url) as conn:
        # Counts and dump share one snapshot, so a restore can be checked row for row even if the app is in use.
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        server = conn.execute("SHOW server_version").fetchone()[0]
        tables = [r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
        counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
        need = pgtools.major(server)
        dump_path = Path(work) / "db.dump"
        pgtools.run("pg_dump", need, ["--format=custom", "--no-owner", "--no-privileges",
                                      f"--snapshot={snapshot}", "--file={work}/db.dump"], database_url, work)
        conn.rollback()
        dump_version = pgtools.version("pg_dump", need)
        digest, dump_bytes = sha256(dump_path), dump_path.stat().st_size
        log(f"database: {len(tables)} tables, {sum(counts.values())} rows, dump {dump_bytes / 1e6:.2f} MB "
            f"(Postgres {server}, {dump_version})")
        blob = bucket.blob(prefix + "db.dump")
        blob.upload_from_filename(str(dump_path), content_type="application/octet-stream", if_generation_match=0)
        blob.reload()
        if blob.size != dump_bytes:
            raise RuntimeError(f"uploaded dump is {blob.size} bytes, expected {dump_bytes}")

    n, size, problems = _copy_objects(cl, source_bucket, backup_bucket, prefix, log)
    if problems:
        raise RuntimeError(f"{len(problems)} object(s) did not copy intact, e.g. {problems[0]}; no manifest written")

    manifest = {
        "stamp": stamp,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "database": {"server_version": server, "pg_dump": dump_version, "pg_dump_major": pgtools.major(dump_version),
                     "tables": counts, "dump": {"key": prefix + "db.dump", "bytes": dump_bytes, "sha256": digest}},
        "objects": {"source_bucket": source_bucket, "prefix": prefix + "objects/", "count": n, "bytes": size},
    }
    bucket.blob(prefix + MANIFEST).upload_from_string(
        json.dumps(manifest, indent=1), content_type="application/json", if_generation_match=0)
    log(f"backup complete: gs://{backup_bucket}/{prefix}")
    return manifest


def main():
    ap = argparse.ArgumentParser(description="Back up the CognitioFlow database and stored files")
    ap.add_argument("--list", action="store_true", help="list completed backups, newest first")
    a = ap.parse_args()
    source = os.environ.get("SOURCE_BUCKET") or os.environ.get("GCS_BUCKET") or "cognitioflow-user-content"
    target = os.environ.get("BACKUP_BUCKET", "cognitioflow-backups")
    cl = client()
    if a.list:
        for m in list_backups(cl, target):
            rows = sum(m["database"]["tables"].values())
            print(f"{m['stamp']}  {rows:>6} rows  {m['objects']['count']:>4} objects  "
                  f"{(m['database']['dump']['bytes'] + m['objects']['bytes']) / 1e6:7.1f} MB")
        return 0
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    try:
        backup(os.environ["DATABASE_URL"], source, target, cl=cl)
    except (RuntimeError, PreconditionFailed, psycopg.Error) as e:
        print(f"BACKUP FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
