"""
Pytest configuration for CognitioFlow.

Requires docker Postgres to be running:
    docker compose up -d

DATABASE_URL defaults to the local docker instance.
"""
import os
import sys

# Set DATABASE_URL before importing run so the pool connects to the right DB
os.environ.setdefault("DATABASE_URL", "postgresql://cf:cf@localhost:5432/cognitioflow")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
# Phase 4: tests run with the dev bypass; tests/test_auth.py turns auth back on per test
os.environ.setdefault("AUTH", "off")
os.environ.setdefault("ALLOWED_EMAILS", "matej@mgms.eu")  # AUTH=off signs in as its first address
os.environ.setdefault("MATEJ_EMAIL", "matej@mgms.eu")     # owner email for migrate_sqlite.py only

# run.py loads .env.local with override=True, which would point storage at ./data. Remember what this test run asked
# for (e.g. STORAGE=gcs + STORAGE_EMULATOR_HOST for the fake-gcs pass) and re-pin it once run is imported.
import shutil
import tempfile
_TEST_STORAGE = os.environ.get("STORAGE", "local")
_TEST_LOCAL_ROOT = tempfile.mkdtemp(prefix="cf-test-storage-")

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import migrate


def _pg_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Run migrations once per test session; verify idempotency by running twice."""
    migrate.run(_pg_url())
    migrate.run(_pg_url())  # must be a no-op (idempotency check)


@pytest.fixture(scope="session", autouse=True)
def pinned_storage(apply_migrations):
    """Point storage at a throwaway local root (or the fake-gcs bucket) for the whole session."""
    import run  # noqa: F401 — triggers run.py's .env.local load before we pin the storage env
    import storage
    os.environ["STORAGE"] = _TEST_STORAGE
    os.environ["STORAGE_LOCAL_ROOT"] = _TEST_LOCAL_ROOT
    if _TEST_STORAGE == "gcs":
        os.environ.setdefault("GCS_BUCKET", "cf-test")
    storage.reset()
    if _TEST_STORAGE == "gcs" and os.environ.get("STORAGE_EMULATOR_HOST"):
        b = storage.backend()
        if not b.bucket.exists():
            b.client.create_bucket(b.bucket.name)
    yield storage
    storage.reset()
    run._pool.close()  # stop pool threads cleanly instead of timing out at interpreter exit
    shutil.rmtree(_TEST_LOCAL_ROOT, ignore_errors=True)


_TRUNCATE = ("TRUNCATE courses, files, messages, notes, cards, reviews, "
             "note_versions, recordings, sessions, users, jobs, "
             "card_distractors, hint_cache, essay_questions, essay_attempts, note_audio CASCADE")


@pytest.fixture(scope="session")
def _truncate_conn(apply_migrations):
    """One connection for the per-test cleanup. In CI the database is a Neon branch across the Atlantic,
    and opening a fresh TLS connection after every test is slow. Holder list so a dropped connection
    can be replaced for the rest of the session."""
    holder = [psycopg.connect(_pg_url(), autocommit=True)]
    yield holder
    holder[0].close()


@pytest.fixture(autouse=True)
def clean_tables(_truncate_conn):
    """Truncate all user-data tables after each test."""
    yield
    try:
        _truncate_conn[0].execute(_TRUNCATE)
    except psycopg.OperationalError:  # the server dropped the connection (idle timeout, compute restart)
        _truncate_conn[0].close()
        _truncate_conn[0] = psycopg.connect(_pg_url(), autocommit=True)
        _truncate_conn[0].execute(_TRUNCATE)


@pytest.fixture
def client():
    # Import here so env vars are already set
    from run import app, init
    init()  # seed courses if empty
    return TestClient(app)


@pytest.fixture
def pg():
    """Direct psycopg connection for assertions."""
    with psycopg.connect(_pg_url()) as conn:
        yield conn
