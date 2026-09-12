"""Two instances cold-starting together must not both apply the same migration."""
import os
import threading
import uuid
from urllib.parse import quote

import psycopg
import pytest

import migrate


def test_concurrent_runs_apply_each_migration_once():
    base = os.environ["DATABASE_URL"]
    schema = f"migtest_{uuid.uuid4().hex[:8]}"
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}options={quote(f'-csearch_path={schema}')}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    try:
        with psycopg.connect(url) as probe:
            if probe.execute("SELECT current_schema()").fetchone()[0] != schema:
                pytest.skip("server ignores the search_path startup option (e.g. a pooled URL)")
        errors = []
        def worker():
            try: migrate.run(url)
            except Exception as e: errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors, errors
        with psycopg.connect(url) as conn:
            applied = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        files = sorted(f.stem for f in (migrate.Path(migrate.__file__).parent / "migrations").glob("*.sql"))
        assert applied == files
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
