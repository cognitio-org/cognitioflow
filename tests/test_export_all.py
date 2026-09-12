"""Tests: scripts/export_all.py — the plain-files exit."""
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

import storage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import export_all  # noqa: E402


def _seed(client):
    courses = client.get("/api/courses").json()
    cid, name = courses[0]["id"], courses[0]["name"]
    client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1 — goods", "body": "# Goods\n*Dassonville* (8/74) [WG]"})
    client.post(f"/api/courses/{cid}/notes", json={"title": "Week 1 — goods", "body": "same title, second note"})
    client.post(f"/api/courses/{cid}/cards", json={"front": "Which case defines MEQRs?", "back": "Dassonville", "week": "1", "source": "manual"})
    fid = client.post(f"/api/courses/{cid}/files", files={"file": ("W1 slides.txt", io.BytesIO(b"Art 34 TFEU"), "text/plain")}, data={"week": "1"}).json()["id"]
    nid = client.post(f"/api/courses/{cid}/notes", json={"title": "Lecture 3", "body": "# Lecture 3"}).json()["id"]
    rid = client.post(f"/api/notes/{nid}/recordings/start").json()["id"]
    client.post(f"/api/recordings/{rid}/finish", files={"audio": ("r.webm", io.BytesIO(b"webm-audio"), "audio/webm")}, data={"seconds": "3", "auto": "0"})
    client.post(f"/api/courses/{cid}/sessions/log", json={"minutes": 30, "topic": "Drill goods"})
    return cid, name, fid


def test_export_writes_readable_course_folders(client, tmp_path):
    cid, name, _ = _seed(client)
    assert export_all.export(tmp_path / "out", log=lambda *_: None) == 0
    course = tmp_path / "out" / name
    assert (course / "notes" / "Week 1 — goods.md").read_text() == "# Goods\n*Dassonville* (8/74) [WG]"
    assert (course / "notes" / "Week 1 — goods (2).md").read_text() == "same title, second note"
    cards = list(csv.DictReader((course / "cards.csv").open()))
    assert [(r["front"], r["back"], r["week"]) for r in cards] == [("Which case defines MEQRs?", "Dassonville", "1")]
    assert (course / "files" / "week 1" / "W1 slides.txt").read_bytes() == b"Art 34 TFEU"
    audio = list((course / "audio" / "Lecture 3").glob("*.webm"))
    assert len(audio) == 1 and audio[0].read_bytes() == b"webm-audio"
    assert "Drill goods" in (course / "sessions.csv").read_text()
    assert "## Tutor prompt" in (course / "course.md").read_text()
    assert "- notes: 3" in (course / "README.md").read_text()
    assert (tmp_path / "out" / "README.md").exists()
    assert len([p for p in (tmp_path / "out").iterdir() if p.is_dir()]) == len(client.get("/api/courses").json())


def test_export_single_course_without_binaries(client, tmp_path):
    cid, name, _ = _seed(client)
    assert export_all.export(tmp_path / "out", course_id=cid, audio=False, files=False, log=lambda *_: None) == 0
    dirs = [p.name for p in (tmp_path / "out").iterdir() if p.is_dir()]
    assert dirs == [name]
    assert not (tmp_path / "out" / name / "files").exists() and not (tmp_path / "out" / name / "audio").exists()


def test_missing_stored_file_is_reported_and_cli_exits_1(client, pg, tmp_path):
    cid, name, fid = _seed(client)
    storage.delete(pg.execute("SELECT key FROM files WHERE id=%s", (fid,)).fetchone()[0])
    lines = []
    assert export_all.export(tmp_path / "a", log=lines.append) == 1
    assert any("W1 slides.txt" in line and "missing" in line for line in lines)
    r = subprocess.run([sys.executable, "scripts/export_all.py", "--out", str(tmp_path / "b")], cwd=ROOT,
                       env=os.environ.copy(), capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr


def test_cli_refuses_a_non_empty_folder(tmp_path):
    (tmp_path / "keep.txt").write_text("x")
    r = subprocess.run([sys.executable, "scripts/export_all.py", "--out", str(tmp_path)], cwd=ROOT,
                       env=os.environ.copy(), capture_output=True, text=True)
    assert r.returncode == 2 and "not empty" in r.stderr
