"""
Migrate CognitioFlow SQLite data into Postgres.

Usage:
    python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db --dry-run
    python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db

Reads MATEJ_EMAIL and DATABASE_URL from the environment (or .env.local).
Never modifies the SQLite source. Never copies files or audio (Phase 2).
Idempotent: uses ON CONFLICT (id) DO NOTHING.
Exits non-zero if any table row count differs between source and destination.
"""
import argparse
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env.local", override=True)
load_dotenv()

# Tables in FK-safe insertion order
TABLES = [
    "courses",
    "files",
    "messages",
    "notes",
    "cards",
    "sessions",
    "note_versions",
    "recordings",
    "reviews",
]


def migrate(sqlite_path: str, dry_run: bool) -> None:
    import psycopg

    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        raise SystemExit("DATABASE_URL is not set.")

    matej_email = os.environ.get("MATEJ_EMAIL")
    if not matej_email:
        raise SystemExit("MATEJ_EMAIL is not set.")

    src_path = Path(sqlite_path).expanduser()
    if not src_path.exists():
        raise SystemExit(f"SQLite file not found: {src_path}")

    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row

    print(f"{'[DRY RUN] ' if dry_run else ''}Migrating {src_path} → Postgres")
    print()

    results: dict[str, tuple[int, int | None]] = {}

    with psycopg.connect(pg_url) as conn:
        # ---- upsert the owner user -----------------------------------------
        user_id: str
        if not dry_run:
            tentative_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO users(id, email, name, created) VALUES(%s, %s, %s, %s) "
                "ON CONFLICT (email) DO NOTHING",
                (tentative_id, matej_email, "Matej", time.time()),
            )
            row = conn.execute(
                "SELECT id FROM users WHERE email=%s", (matej_email,)
            ).fetchone()
            user_id = row[0]
            conn.commit()
            print(f"  users: owner user_id={user_id}")
        else:
            user_id = "<dry-run-id>"
            print(f"  users: would create/find owner for {matej_email}")

        # ---- migrate each table --------------------------------------------
        for table in TABLES:
            src_rows = src.execute(f"SELECT * FROM {table}").fetchall()
            src_count = len(src_rows)

            if dry_run:
                print(f"  {table:20s}: src={src_count:6d}  (would insert)")
                results[table] = (src_count, None)
                continue

            for row in src_rows:
                d = dict(row)
                # Attach user_id to courses
                if table == "courses":
                    d["user_id"] = user_id

                cols = list(d.keys())
                vals = list(d.values())
                placeholders = ", ".join(["%s"] * len(cols))
                col_sql = ", ".join(cols)

                try:
                    conn.execute(
                        f"INSERT INTO {table}({col_sql}) VALUES({placeholders}) "
                        f"ON CONFLICT (id) DO NOTHING",
                        vals,
                    )
                except Exception as exc:
                    row_id = d.get("id", "?")
                    print(f"  WARNING: {table} id={row_id}: {exc}", file=sys.stderr)

            conn.commit()

            dst_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            match = "✓" if src_count == dst_count else "✗ MISMATCH"
            print(f"  {table:20s}: src={src_count:6d}  dst={dst_count:6d}  {match}")
            results[table] = (src_count, dst_count)

    print()
    if dry_run:
        print("Dry run complete — no rows written.")
        return

    mismatches = [t for t, (s, d) in results.items() if d is not None and s != d]
    if mismatches:
        print(f"FAILED — row count mismatch: {', '.join(mismatches)}", file=sys.stderr)
        sys.exit(1)

    print("Migration complete — all counts match.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite → Postgres")
    parser.add_argument("--sqlite", required=True, help="Path to cognitioflow.db")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, write nothing")
    args = parser.parse_args()
    migrate(args.sqlite, args.dry_run)
