"""
Migration runner — applies pending .sql files in migrations/ to DATABASE_URL.

Usage:
    python -m migrate          # apply pending migrations
    python migrate.py          # same
"""
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env.local", override=True)
load_dotenv()


def run(database_url: str | None = None) -> None:
    import psycopg

    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set.")

    migrations_dir = Path(__file__).parent / "migrations"

    with psycopg.connect(url) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at DOUBLE PRECISION
            )
        """)
        conn.commit()

        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

        files = sorted(
            f for f in migrations_dir.glob("*.sql")
            if re.match(r"^\d+", f.name)
        )

        for f in files:
            version = f.stem
            if version in applied:
                print(f"  skip  {version} (already applied)")
                continue

            print(f"  apply {version} …", end="", flush=True)
            sql = f.read_text(encoding="utf-8")

            # Execute each statement individually (psycopg3 has no executescript).
            # Strip comment lines first so they don't swallow the first real statement.
            clean = "\n".join(
                line for line in sql.splitlines()
                if not line.strip().startswith("--")
            )
            for stmt in clean.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)

            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES(%s, %s)",
                (version, time.time()),
            )
            conn.commit()
            print(" done")

    print("Migrations complete.")


if __name__ == "__main__":
    run()
