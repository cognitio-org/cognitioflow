#!/usr/bin/env python3
"""
Plain-files exit from CognitioFlow: every course as a folder you can open without the app.

  python3 scripts/export_all.py --out ~/CognitioFlow-export-2026-09-12
  python3 scripts/export_all.py --out ~/cf-eu --course eu --no-audio --no-files

Per course (a folder named after the course):
  README.md          what's in the folder, with counts
  course.md          name, tutor prompt (and the course brief when there is one)
  notes/*.md         each note's Markdown, exactly as written
  cards.csv          front, back, week, source, due, ease, interval, reps
  sessions.csv       planner sessions
  tutor-chat.md      the tutor conversation
  files/<week>/…     uploaded originals, fetched from storage
  audio/<note>/…     lecture recordings, fetched from storage

Environment: DATABASE_URL and the STORAGE settings. The repo's .env.local fills in anything the shell doesn't set.
Everything is written through storage.LocalStorage, so no path to user content is built outside storage.py.
Exits 1 if any stored file or recording is missing.
"""
import argparse
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

import storage  # noqa: E402

MD, TXT, CSV = "text/markdown; charset=utf-8", "text/plain; charset=utf-8", "text/csv; charset=utf-8"


def _unique(used: set, name: str) -> str:
    """name, or name (2), name (3)… — case-insensitively unique within one folder."""
    stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
    candidate, i = name, 2
    while candidate.lower() in used:
        candidate = f"{stem} ({i}).{ext}" if dot else f"{name} ({i})"
        i += 1
    used.add(candidate.lower())
    return candidate


def _label(text, fallback: str) -> str:
    return storage.safe_name(text, 120) if (text or "").strip() else fallback


def _csv(columns, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in columns])
    return buf.getvalue()


def export(out_dir, course_id=None, audio=True, files=True, database_url=None, log=print) -> int:
    """Write the export under out_dir. Returns the number of stored objects that couldn't be read."""
    out = storage.LocalStorage(Path(out_dir).expanduser())
    missing, stamp, summary = 0, time.strftime("%Y-%m-%d %H:%M"), []
    with psycopg.connect(database_url or os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        q = "SELECT * FROM courses" + (" WHERE id=%s" if course_id else "") + " ORDER BY created"
        courses = conn.execute(q, (course_id,) if course_id else ()).fetchall()
        if course_id and not courses:
            raise SystemExit(f"No course with id {course_id!r}.")
        used_courses = set()
        for c in courses:
            folder = _unique(used_courses, _label(c["name"], c["id"]))

            # folder bound as a default: the closure would otherwise read whatever `folder` held
            # when it was called, not when it was defined, and write into the wrong course.
            def put(rel, data, ctype=TXT, folder=folder):
                out.put(f"{folder}/{rel}", data if isinstance(data, bytes) else data.encode("utf-8"), ctype)

            lines = [f"# {c['name']}", "", f"- Course id: `{c['id']}`", f"- Exported: {stamp}"]
            if c.get("brief"):
                lines += ["", "## Course brief", "", "```json", json.dumps(c["brief"], indent=2, ensure_ascii=False), "```"]
            lines += ["", "## Tutor prompt", "", c.get("tutor_prompt") or "_(none)_", ""]
            put("course.md", "\n".join(lines), MD)

            notes = conn.execute("SELECT id, title, body FROM notes WHERE course_id=%s ORDER BY updated", (c["id"],)).fetchall()
            used_notes, note_label = set(), {}
            for n in notes:
                name = _unique(used_notes, _label(n["title"], n["id"]) + ".md")
                note_label[n["id"]] = name[:-3]
                put(f"notes/{name}", n["body"] or "", MD)

            cards = conn.execute("SELECT * FROM cards WHERE course_id=%s ORDER BY created", (c["id"],)).fetchall()
            put("cards.csv", _csv(["front", "back", "week", "source", "due", "ease", "interval", "reps"], cards), CSV)
            sessions = conn.execute("SELECT * FROM sessions WHERE course_id=%s ORDER BY day", (c["id"],)).fetchall()
            put("sessions.csv", _csv(["day", "topic", "minutes", "done"], sessions), CSV)
            messages = conn.execute("SELECT role, content, created FROM messages WHERE course_id=%s ORDER BY created", (c["id"],)).fetchall()
            chat = [f"# Tutor conversation — {c['name']}", ""]
            for m in messages:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["created"] or 0))
                chat += [f"### {'You' if m['role'] == 'user' else 'Tutor'} · {when}", "", m["content"] or "", ""]
            put("tutor-chat.md", "\n".join(chat), MD)

            n_files = n_audio = 0
            if files:
                used_by_week = {}
                for f in conn.execute("SELECT id, name, week, key FROM files WHERE course_id=%s ORDER BY created", (c["id"],)).fetchall():
                    if not f["key"]:
                        continue
                    try:
                        data = storage.get(f["key"])
                    except storage.NotFound:
                        missing += 1; log(f"  ✗ {c['name']}: file {f['name']!r} ({f['key']}) is missing from storage"); continue
                    week = f"week {f['week']}" if f["week"] else "unsorted"
                    name = _unique(used_by_week.setdefault(week, set()), _label(f["name"], f["id"]))
                    put(f"files/{storage.safe_name(week)}/{name}", data, "application/octet-stream"); n_files += 1
            if audio:
                rows = conn.execute("SELECT r.id, r.key, r.started, r.note_id FROM recordings r JOIN notes n ON n.id = r.note_id "
                                    "WHERE n.course_id=%s AND r.key <> '' ORDER BY r.started", (c["id"],)).fetchall()
                for r in rows:
                    try:
                        data = storage.get(r["key"])
                    except storage.NotFound:
                        missing += 1; log(f"  ✗ {c['name']}: recording {r['id']} ({r['key']}) is missing from storage"); continue
                    when = time.strftime("%Y-%m-%d %H%M", time.localtime(r["started"] or 0))
                    put(f"audio/{note_label.get(r['note_id'], r['note_id'])}/{when} {r['id']}.webm", data, "audio/webm"); n_audio += 1

            counts = {"notes": len(notes), "cards": len(cards), "sessions": len(sessions), "tutor messages": len(messages),
                      "files": n_files if files else "skipped", "recordings": n_audio if audio else "skipped"}
            put("README.md", "\n".join([f"# {c['name']} — CognitioFlow export", "", f"Exported {stamp}.", ""]
                                       + [f"- {k}: {v}" for k, v in counts.items()] + [""]), MD)
            summary.append((folder, counts))
            log(f"  {folder}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    out.put("README.md", "\n".join(["# CognitioFlow export", "", f"Exported {stamp}.", ""]
                                   + [f"- [{f}]({f.replace(' ', '%20')}/README.md)" for f, _ in summary] + [""]).encode(), MD)
    return missing


def main():
    load_dotenv(ROOT / ".env.local")  # fills gaps only; shell variables win
    load_dotenv()
    ap = argparse.ArgumentParser(description="Export every course as plain files (Markdown, CSV, originals, audio)")
    ap.add_argument("--out", required=True, help="folder to create (must be empty or not exist)")
    ap.add_argument("--course", help="export only this course id")
    ap.add_argument("--no-audio", action="store_true", help="skip lecture recordings")
    ap.add_argument("--no-files", action="store_true", help="skip uploaded originals")
    a = ap.parse_args()
    target = Path(a.out).expanduser()
    if target.exists() and any(target.iterdir()):
        ap.error(f"{target} is not empty — choose a new folder")
    print(f"Exporting to {target} (STORAGE={os.environ.get('STORAGE', 'local')})")
    missing = export(target, a.course, audio=not a.no_audio, files=not a.no_files)
    if missing:
        print(f"Done with {missing} missing object(s) — see ✗ lines above.", file=sys.stderr)
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
