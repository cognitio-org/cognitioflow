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


@pytest.fixture(autouse=True)
def clean_tables(apply_migrations):
    """Truncate all user-data tables before each test."""
    yield
    with psycopg.connect(_pg_url()) as conn:
        conn.execute(
            "TRUNCATE courses, files, messages, notes, cards, reviews, "
            "note_versions, recordings, sessions, users CASCADE"
        )
        conn.commit()


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
