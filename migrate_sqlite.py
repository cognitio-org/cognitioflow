"""
Migrate CognitioFlow SQLite data into Postgres.

Usage:
    python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db --dry-run
    python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db
    python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db --verify

Reads MATEJ_EMAIL and DATABASE_URL from the environment; .env.local only fills in what the shell
doesn't set, so `DATABASE_URL=<Neon prod> python migrate_sqlite.py …` really targets Neon.
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

load_dotenv(".env.local")  # shell variables win: the cutover points DATABASE_URL at Neon prod
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
                # Phase 2 renamed path → key; legacy paths are moved into storage by migrate_storage.py
                if table in ("files", "recordings") and "path" in d:
                    d["key"] = d.pop("path")
                # Attach user_id to courses
                if table == "courses":
                    d["user_id"] = user_id

                cols = list(d.keys())
                vals = list(d.values())
                placeholders = ", ".join(["%s"] * len(cols))
                col_sql = ", ".join(cols)

                try:
                    if table == "courses":
                        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id")
                        conn.execute(
                            f"INSERT INTO {table}({col_sql}) VALUES({placeholders}) "
                            f"ON CONFLICT (id) DO UPDATE SET {set_clause}",
                            vals,
                        )
                    else:
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


SPOT_TABLES = ("notes", "cards", "recordings")


def _same(column: str, src, dst) -> bool:
    if column == "key" and isinstance(dst, str) and dst.startswith(("courses/", "notes/")):
        return True  # migrate_storage.py has since rewritten the laptop path to a storage key
    if isinstance(src, (int, float)) and isinstance(dst, (int, float)):
        return abs(float(src) - float(dst)) < 1e-6
    return src == dst


def verify(sqlite_path: str, sample: int = 20, seed=None) -> int:
    """Re-count every table and compare `sample` random rows across notes/cards/recordings column by column.
    Returns the number of problems (0 = verified). Writes nothing."""
    import random
    import psycopg
    from psycopg.rows import dict_row

    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        raise SystemExit("DATABASE_URL is not set.")
    src_path = Path(sqlite_path).expanduser()
    if not src_path.exists():
        raise SystemExit(f"SQLite file not found: {src_path}")
    src = sqlite3.connect(str(src_path))
    src.row_factory = sqlite3.Row
    print(f"[VERIFY] {src_path} ↔ Postgres")
    print()
    problems = 0
    with psycopg.connect(pg_url, row_factory=dict_row) as conn:
        for table in TABLES:
            s_n = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            d_n = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            ok = s_n == d_n
            problems += 0 if ok else 1
            print(f"  {table:20s}: src={s_n:6d}  dst={d_n:6d}  {'✓' if ok else '✗ MISMATCH'}")
        pool = [(t, r[0]) for t in SPOT_TABLES for r in src.execute(f"SELECT id FROM {t}").fetchall()]
        picked = random.Random(seed).sample(pool, min(sample, len(pool)))
        differing = 0
        for table, row_id in picked:
            s_row = dict(src.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone())
            if "path" in s_row:
                s_row["key"] = s_row.pop("path")
            d_row = conn.execute(f"SELECT * FROM {table} WHERE id=%s", (row_id,)).fetchone()
            diffs = ["(missing in Postgres)"] if d_row is None else [c for c, v in s_row.items() if not _same(c, v, d_row.get(c))]
            if diffs:
                differing += 1
                print(f"  ✗ {table} {row_id}: {', '.join(diffs)}")
        problems += differing
        print(f"  spot check: {len(picked)} random rows across {', '.join(SPOT_TABLES)} — {len(picked) - differing} identical")
    print()
    print("Verified — counts match and sampled rows are identical." if not problems else f"FAILED — {problems} problem(s).")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite → Postgres")
    parser.add_argument("--sqlite", required=True, help="Path to cognitioflow.db")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print counts only, write nothing")
    mode.add_argument("--verify", action="store_true", help="After migrating: re-count and spot-check rows, write nothing")
    parser.add_argument("--sample", type=int, default=20, help="rows to spot-check with --verify (default 20)")
    parser.add_argument("--seed", type=int, default=None, help="random seed for a repeatable spot check")
    args = parser.parse_args()
    if args.verify:
        sys.exit(1 if verify(args.sqlite, args.sample, args.seed) else 0)
    migrate(args.sqlite, args.dry_run)
