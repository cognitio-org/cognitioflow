"""Tests: the connection pool survives the database killing its connections (Neon suspends idle computes)."""
import psycopg


def test_request_after_server_kills_pooled_connections(client, pg):
    assert client.get("/api/courses").status_code == 200  # the pool now holds an open connection
    killed = pg.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
    ).fetchall()
    pg.commit()
    assert len(killed) >= 1
    r = client.get("/api/courses")  # used to be a 500: psycopg.errors.AdminShutdown on a dead pooled connection
    assert r.status_code == 200


def test_pool_is_configured_to_check_connections():
    import run
    assert run._pool._check is not None and run._pool.max_idle == 240
