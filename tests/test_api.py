"""Smoke tests for the main API endpoints."""
import json
import os
import time
import unittest.mock as mock
from datetime import date

import psycopg
from fastapi.testclient import TestClient


def _pg_url() -> str:
    return os.environ["DATABASE_URL"]


# ---------------------------------------------------------------- helpers

def _course_id(client: TestClient) -> str:
    """Return the 'eu' course id (seeded by init())."""
    r = client.get("/api/courses")
    assert r.status_code == 200
    return next(c["id"] for c in r.json() if c["id"] == "eu")


# ---------------------------------------------------------------- courses

def test_create_course(client: TestClient):
    r = client.post("/api/courses", json={"name": "Test", "accent": "#f00", "tutor_prompt": ""})
    assert r.status_code == 200
    cid = r.json()["id"]
    r2 = client.get("/api/courses")
    assert any(c["id"] == cid for c in r2.json())


# ---------------------------------------------------------------- files

def test_create_file_record(client: TestClient):
    cid = _course_id(client)
    import io
    data = b"Article 34 TFEU prohibits MEQRs."
    r = client.post(
        f"/api/courses/{cid}/files",
        files={"file": ("week1.txt", io.BytesIO(data), "text/plain")},
        data={"week": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "indexed"
    assert body["chars"] > 0


def test_list_files_by_week(client: TestClient):
    cid = _course_id(client)
    import io
    for wk in ("1", "1", "2"):
        client.post(
            f"/api/courses/{cid}/files",
            files={"file": (f"w{wk}.txt", io.BytesIO(b"x"), "text/plain")},
            data={"week": wk},
        )

    r = client.get(f"/api/courses/{cid}/files")
    assert r.status_code == 200
    files = r.json()
    wk1 = [f for f in files if f["week"] == "1"]
    assert len(wk1) == 2


def test_file_label_role_and_week_edit(client: TestClient):
    """An upload arrives titled and typed, and every part of that is correctable by hand."""
    cid = _course_id(client)
    import io
    r = client.post(
        f"/api/courses/{cid}/files",
        files={"file": ("W2_WG complete notes.pdf", io.BytesIO(b"Dassonville and Keck."), "text/plain")},
        data={"week": ""},
    )
    fid = r.json()["id"]
    f = next(x for x in client.get(f"/api/courses/{cid}/files").json() if x["id"] == fid)
    assert f["label"] == "W2 WG complete notes"      # readable: no extension, no underscores
    assert f["role"] == "wg"                         # the tutor's top authority, recognised from the name

    assert client.post(f"/api/files/{fid}/meta", json={"label": "Week 2 working group", "week": "2"}).status_code == 200
    f = next(x for x in client.get(f"/api/courses/{cid}/files").json() if x["id"] == fid)
    assert (f["label"], f["week"], f["role"]) == ("Week 2 working group", "2", "wg")

    assert client.post(f"/api/files/{fid}/meta", json={"week": "99"}).status_code == 400
    assert client.post(f"/api/files/{fid}/meta", json={"role": "nonsense"}).status_code == 400
    assert client.post(f"/api/files/{fid}/meta", json={"week": ""}).status_code == 200   # back to unsorted is allowed


# ---------------------------------------------------------------- cards / SM-2

def test_create_card(client: TestClient):
    cid = _course_id(client)
    r = client.post(
        f"/api/courses/{cid}/cards",
        json={"front": "What is Art 34?", "back": "MEQR prohibition", "source": "test"},
    )
    assert r.status_code == 200
    kid = r.json()["id"]

    r2 = client.get(f"/api/courses/{cid}/cards")
    cards = r2.json()
    card = next(c for c in cards if c["id"] == kid)
    assert card["due"] == date.today().isoformat()  # ISO string, not a float


def test_review_updates_sm2_fields(client: TestClient, monkeypatch):
    """SM-2's own arithmetic, asserted with SM-2 selected (FSRS is the default and schedules differently)."""
    import schedule
    monkeypatch.setattr(schedule, "BACKEND", "sm2")
    cid = _course_id(client)
    r = client.post(
        f"/api/courses/{cid}/cards",
        json={"front": "Q", "back": "A"},
    )
    kid = r.json()["id"]

    # Rating 2 = "good"
    r2 = client.post(f"/api/cards/{kid}/review", json={"rating": 2})
    assert r2.status_code == 200
    body = r2.json()
    assert body["interval"] == 1
    assert body["due"] > date.today().isoformat()  # due in the future

    # Check DB directly
    with psycopg.connect(_pg_url()) as conn:
        row = conn.execute(
            "SELECT ease, interval, reps, due FROM cards WHERE id=%s", (kid,)
        ).fetchone()
    assert row[3] == body["due"]  # due is ISO TEXT
    assert row[2] == 1            # reps incremented


def test_list_due_cards(client: TestClient):
    cid = _course_id(client)
    # Create a card and immediately rate it with 0 (reset → due today)
    r = client.post(f"/api/courses/{cid}/cards", json={"front": "Q", "back": "A"})
    kid = r.json()["id"]
    client.post(f"/api/cards/{kid}/review", json={"rating": 0})

    r2 = client.get(f"/api/courses/{cid}/cards", params={"due": 1})
    assert r2.status_code == 200
    ids = [c["id"] for c in r2.json()]
    assert kid in ids


# ---------------------------------------------------------------- notes + version history

def test_create_edit_note_and_versions(client: TestClient):
    cid = _course_id(client)

    # Create
    r = client.post(f"/api/courses/{cid}/notes", json={"title": "EU Law", "body": "draft v1"})
    assert r.status_code == 200
    nid = r.json()["id"]

    # Read
    r2 = client.get(f"/api/notes/{nid}")
    assert r2.json()["body"] == "draft v1"

    # First save — no version yet (body changed but no prior version)
    time.sleep(0)  # no throttle needed for first save
    client.put(f"/api/notes/{nid}", json={"title": "EU Law", "body": "draft v2"})

    # Versions list
    r3 = client.get(f"/api/notes/{nid}/versions")
    # First save snapshots original body IF it was non-empty; confirm endpoint works
    assert r3.status_code == 200


def test_note_version_restore(client: TestClient):
    cid = _course_id(client)
    r = client.post(f"/api/courses/{cid}/notes", json={"title": "T", "body": "original"})
    nid = r.json()["id"]

    # Force a version by making the note old enough via direct DB update
    with psycopg.connect(_pg_url()) as conn:
        conn.execute(
            "INSERT INTO note_versions(id, note_id, title, body, created) VALUES(%s,%s,%s,%s,%s)",
            ("vid1", nid, "T", "original", time.time() - 200),
        )
        conn.commit()

    client.put(f"/api/notes/{nid}", json={"title": "T", "body": "updated"})

    vids = client.get(f"/api/notes/{nid}/versions").json()
    assert len(vids) >= 1

    # Restore first version
    vid = vids[-1]["id"]  # oldest
    r2 = client.post(f"/api/notes/{nid}/restore/{vid}")
    assert r2.status_code == 200

    r3 = client.get(f"/api/notes/{nid}")
    assert r3.json()["body"] == "original"


# ---------------------------------------------------------------- sessions CRUD

def test_sessions_crud(client: TestClient):
    cid = _course_id(client)

    # Create
    r = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day": "2026-09-15", "topic": "Art 34 drill", "minutes": 45},
    )
    assert r.status_code == 200
    sid = r.json()["id"]

    # List
    r2 = client.get("/api/sessions")
    ids = [s["id"] for s in r2.json()]
    assert sid in ids

    # Toggle done
    r3 = client.post(f"/api/sessions/{sid}/toggle")
    assert r3.status_code == 200
    with psycopg.connect(_pg_url()) as conn:
        done = conn.execute("SELECT done FROM sessions WHERE id=%s", (sid,)).fetchone()[0]
    assert done == 1

    # Delete
    client.delete(f"/api/sessions/{sid}")
    with psycopg.connect(_pg_url()) as conn:
        row = conn.execute("SELECT id FROM sessions WHERE id=%s", (sid,)).fetchone()
    assert row is None


# ---------------------------------------------------------------- planner (model mocked)

def test_auto_plan_no_model_call(client: TestClient):
    """Planner endpoint must succeed with a mocked model (no real API call)."""
    cid = _course_id(client)

    fake_sessions = json.dumps([
        {"day": "2026-09-16", "topic": "Art 34 scope", "minutes": 45},
        {"day": "2026-09-17", "topic": "Recall cards", "minutes": 20},
    ])

    fake_msg = mock.MagicMock()
    fake_msg.content = [mock.MagicMock(type="text", text=fake_sessions)]

    fake_client = mock.MagicMock()
    fake_client.messages.create.return_value = fake_msg

    import run
    with mock.patch.object(run, "client", return_value=fake_client):
        r = client.post(
            f"/api/courses/{cid}/plan",
            json={"start": "2026-09-15", "days": 7, "minutes_per_day": 90},
        )

    assert r.status_code == 200
    assert r.json()["added"] == 2

    r2 = client.get("/api/sessions")
    topics = [s["topic"] for s in r2.json()]
    assert "Art 34 scope" in topics


# ---------------------------------------------------------------- due-card bug fix

def test_due_cards_uses_iso_date_not_float(client: TestClient):
    """
    Regression: planner and stats must compare cards.due (TEXT ISO) with today's
    ISO date string, not time.time() (float).  A card due today must appear in
    the due list.
    """
    cid = _course_id(client)
    r = client.post(f"/api/courses/{cid}/cards", json={"front": "Q", "back": "A"})
    kid = r.json()["id"]

    # Set due to today explicitly
    with psycopg.connect(_pg_url()) as conn:
        conn.execute(
            "UPDATE cards SET due=%s WHERE id=%s",
            (date.today().isoformat(), kid),
        )
        conn.commit()

    r2 = client.get(f"/api/courses/{cid}/cards", params={"due": 1})
    ids = [c["id"] for c in r2.json()]
    assert kid in ids, "Card due today must appear in the due-cards list"

    # stats endpoint must also count it
    r3 = client.get(f"/api/courses/{cid}/stats")
    assert r3.json()["due"] >= 1
