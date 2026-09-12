#!/usr/bin/env python3
"""
One-shot: move the laptop build's uploaded files and lecture audio into storage under the Phase 2 key layout.

  python migrate_storage.py --data ~/Desktop/cognitioflow/data --dry-run   # counts only, writes nothing
  python migrate_storage.py --data ~/Desktop/cognitioflow/data             # upload + rewrite keys
  python migrate_storage.py --verify                                       # every key exists in storage

Environment: DATABASE_URL, STORAGE (+ GCS_BUCKET or STORAGE_LOCAL_ROOT). .env.local is read if present;
variables already set in the shell win.

After migrate_sqlite.py, files.key / recordings.key still hold the old absolute paths. For each such row the old
file is found by name under --data/uploads or --data/audio, uploaded to courses/{cid}/files/{fid}/{name} or
notes/{nid}/audio/{rid}.webm, and the row's key rewritten. Rows already on the new layout are skipped, so re-running
is safe. Exits non-zero when any row can't be accounted for.
"""
import argparse
import mimetypes
import os
import sys
from pathlib import PurePath

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

import storage

TABLES = {
    "files": ("uploads", "SELECT id, course_id, name, key FROM files ORDER BY created"),
    "recordings": ("audio", "SELECT id, note_id, key FROM recordings ORDER BY started"),
}


def new_key(table: str, row: dict) -> str:
    if table == "recordings":
        return f"notes/{row['note_id']}/audio/{row['id']}.webm"
    old = PurePath(row["key"]).name  # laptop build saved uploads as {fid}_{original name}
    name = old[len(row["id"]) + 1:] if old.startswith(row["id"] + "_") else old
    return f"courses/{row['course_id']}/files/{row['id']}/{storage.safe_name(name)}"


def migrate(data_dir, dry_run: bool = False, verify: bool = False, database_url=None, out=print) -> int:
    """Returns the number of tables whose counts don't reconcile (0 = success)."""
    legacy = storage.LocalStorage(data_dir) if data_dir else None
    problems = 0
    with psycopg.connect(database_url or os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        for table, (folder, query) in TABLES.items():
            moved = already = no_audio = missing = unverified = 0
            for r in conn.execute(query).fetchall():
                key = r["key"] or ""
                if not key:
                    if table == "recordings":
                        no_audio += 1  # recording started but never finished — nothing to move
                    else:
                        missing += 1; out(f"  ✗ {table} {r['id']}: empty key")
                    continue
                if key.startswith(("courses/", "notes/")):
                    if verify and not storage.exists(key):
                        unverified += 1; out(f"  ✗ {table} {r['id']}: {key} not in storage")
                    else:
                        already += 1
                    continue
                if verify:
                    unverified += 1; out(f"  ✗ {table} {r['id']}: still a legacy path")
                    continue
                src = f"{folder}/{PurePath(key).name}"
                if legacy is None or not legacy.exists(src):
                    missing += 1; out(f"  ✗ {table} {r['id']}: {src} not found under --data")
                    continue
                if not dry_run:
                    target = new_key(table, r)
                    ctype = "audio/webm" if table == "recordings" else (mimetypes.guess_type(target)[0] or "application/octet-stream")
                    storage.put(target, legacy.get(src), ctype)
                    conn.execute(f"UPDATE {table} SET key=%s WHERE id=%s", (target, r["id"]))
                    conn.commit()  # per row, so an interrupted run resumes where it stopped
                moved += 1
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            ok = moved + already + no_audio == count and not missing and not unverified
            problems += 0 if ok else 1
            out(f"  {table:10s}: rows={count:5d}  {'to move' if dry_run else 'moved'}={moved:5d}  already={already:5d}"
                + (f"  no-audio={no_audio}" if table == "recordings" else "")
                + f"  missing={missing}" + (f"  unverified={unverified}" if verify else "")
                + f"  {'✓' if ok else '✗ MISMATCH'}")
    return problems


def main():
    load_dotenv(".env.local")
    load_dotenv()
    ap = argparse.ArgumentParser(description="Move the laptop build's files and audio into storage")
    ap.add_argument("--data", help="the old build's data/ folder (contains uploads/ and audio/)")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    ap.add_argument("--verify", action="store_true", help="check every key exists in storage, write nothing")
    a = ap.parse_args()
    if not a.verify and not a.data:
        ap.error("--data is required (except with --verify)")
    mode = "VERIFY" if a.verify else "DRY RUN" if a.dry_run else "MIGRATE"
    print(f"[{mode}] STORAGE={os.environ.get('STORAGE', 'local')}")
    problems = migrate(a.data, dry_run=a.dry_run, verify=a.verify)
    if problems:
        print("FAILED — counts don't reconcile (see ✗ lines above)", file=sys.stderr)
        sys.exit(1)
    print("OK — every row accounted for.")


if __name__ == "__main__":
    main()
