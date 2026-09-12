"""
CognitioFlow — local study workspace.
Run:  python run.py   then open http://localhost:8000
Everything lives in ./data (SQLite + uploaded files). Nothing leaves your Mac except tutor calls to the Claude API.
"""
import re
import base64, io, json, mimetypes, os, random, tempfile, time, uuid
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import storage
import transcribe as stt

load_dotenv(".env.local", override=True)
load_dotenv()

ROOT = Path(__file__).parent

MODEL = os.environ.get("CF_MODEL", "claude-sonnet-4-6")            # drilling / explaining / notes
CHEAP_MODEL = os.environ.get("CF_CHEAP_MODEL", "claude-haiku-4-5")  # card generation, bulk work
STRONG_MODEL = os.environ.get("CF_STRONG_MODEL", MODEL)              # reconcile only; e.g. claude-fable-5-1 or claude-opus-5
MODELS = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-5", "claude-fable-5-1"]
CONTEXT_CHAR_BUDGET = int(os.environ.get("CF_CONTEXT_CHARS", "180000"))  # ~45k tokens of file text per call
MAX_IMAGES = 6
RECONCILE_TOKENS = 8000   # the cap stays here; the Continue button finishes anything cut off
DRAFT_TOKENS = 4000

# ---------------------------------------------------------------- DB
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is required — copy .env.local.example to .env.local and set it."
    )

# Neon suspends an idle compute after ~5 minutes and kills its connections. Check each connection as it is
# handed out (a dead one is replaced, not given to the request) and close idle ones before Neon does.
_pool = ConnectionPool(_DATABASE_URL, min_size=1, max_size=10, open=True, kwargs={"row_factory": dict_row},
                      check=ConnectionPool.check_connection, max_idle=240)


class _Conn:
    """Wraps a psycopg connection; converts ? placeholders to %s at execute time."""
    def __init__(self, conn):
        self._c = conn

    def execute(self, q, params=()):
        # Escape literal % (e.g. LIKE patterns) before converting ? → %s placeholders
        q = q.replace("%", "%%").replace("?", "%s")
        return self._c.execute(q, params)


@contextmanager
def db():
    """Pooled connection context manager; commits on success, rolls back on exception."""
    with _pool.connection() as conn:
        yield _Conn(conn)


def init():
    import migrate as _migrate
    _migrate.run(_DATABASE_URL)
    with db() as d:
        if not d.execute("SELECT 1 FROM courses LIMIT 1").fetchone():
            d.execute("INSERT INTO courses(id,name,accent,tutor_prompt,created) VALUES(?,?,?,?,?)",
                      ("eu", "European Law", "#24467a", EU_PROMPT, time.time()))
            d.execute("INSERT INTO courses(id,name,accent,tutor_prompt,created) VALUES(?,?,?,?,?)",
                      ("prop", "Property Law", "#2e6b4a", PROP_PROMPT, time.time()))
        # existing installs: fill an empty Property Law prompt from prompts/property_law.md once
        if PROP_PROMPT:
            d.execute("UPDATE courses SET tutor_prompt=? WHERE id='prop' AND (tutor_prompt IS NULL OR tutor_prompt='')",
                      (PROP_PROMPT,))

BASE_PROMPT = """You are the study tutor inside CognitioFlow, a private local workspace for Matej, a law student at the University of Groningen.
Working method (standing instructions):
- Work ONLY from the course files supplied below. Do not introduce cases, articles or authorities that are not in them; if you must mention something outside the files, label it [OUTSIDE FILES].
- Authority hierarchy when sources conflict: annotated working-group notes > lecture slides/transcripts > textbook. Flag divergences explicitly.
- Format replies in Markdown. When structure genuinely helps (a test sequence, a case map, a comparison), draw it as a ```mermaid code block (flowchart TD / LR) — the interface renders it. Keep diagrams small: nodes carry short labels, never paragraphs. Tables for compare-and-contrast.
- Default to Socratic drilling: one sharp question at a time, then firm, specific correction. Test rather than lecture, unless asked to explain or to build notes.
- When building or reconciling notes, tag provenance: [LECTURE] [WG] [SLIDES] [READER] [SCHUTZE] [ADDED].
- Exam answers follow IRAC. Keep prose tight; no filler.
- Matej's input often comes from garbled voice transcription; decode charitably before responding.
"""

_pp = ROOT / "prompts" / "property_law.md"
PROP_PROMPT = _pp.read_text(encoding="utf-8") if _pp.exists() else ""

EU_PROMPT = """Course specifics — European Law (Villanueva; WG tutor Phoebe; Schütze 3rd ed.). Exam: two cases plus compare-and-contrast, IRAC.
Known traps to police every time: contra legem belongs ONLY to indirect effect (Adeneler), never horizontal direct effect or 'sufficiently serious breach'; Dassonville is the Art 34 scope test and Cassis the justification/mutual-recognition step — sequential moves, not opposing integration models; Brasserie du Pêcheur = Factortame (same joined cases); Van Gend concerns Art 30, not Art 34; Chernobyl is C-62/88, never C-70/88.
Every free-movement problem is three moves: (1) catch, (2) justify — Treaty list or open list, (3) proportionality."""

# ---------------------------------------------------------------- text extraction
def extract(path: Path, kind: str) -> str:
    try:
        if kind == "pdf":
            from pypdf import PdfReader
            r = PdfReader(str(path)); return "\n\n".join((p.extract_text() or "") for p in r.pages)
        if kind == "pptx":
            from pptx import Presentation
            out = []
            for i, s in enumerate(Presentation(str(path)).slides, 1):
                bits = [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
                if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
                    bits.append("[notes] " + s.notes_slide.notes_text_frame.text)
                out.append(f"--- slide {i} ---\n" + "\n".join(bits))
            return "\n\n".join(out)
        if kind == "docx":
            import docx
            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
        if kind == "text":
            return path.read_text(errors="ignore")
    except Exception as e:
        return f"[extraction failed: {e}]"
    return ""

def extract_bytes(data: bytes, name: str, kind: str) -> str:
    """extract() for uploaded bytes. pypdf/python-pptx/python-docx want a path, so they get a temp file that is gone straight after."""
    if kind == "text": return data.decode(errors="ignore")
    with tempfile.NamedTemporaryFile(suffix=Path(name).suffix) as tmp:
        tmp.write(data); tmp.flush()
        return extract(Path(tmp.name), kind)

def serve_object(key: str, request: Request, media_type: str, filename: Optional[str] = None, expires_s: int = 3600):
    """Send a stored object to the browser: redirect to a signed URL where storage can sign one,
    otherwise stream it with byte-range support so <audio> can seek."""
    if not key: raise HTTPException(404)
    signed = storage.url(key, expires_s, filename=filename, content_type=media_type)
    if signed: return RedirectResponse(signed, status_code=302)
    try: size = storage.size(key)
    except storage.NotFound: raise HTTPException(404)
    headers = {"Accept-Ranges": "bytes"}
    if filename: headers["Content-Disposition"] = storage.content_disposition(filename)
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("range", "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1): start, end = int(m.group(1)), min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        else: start, end = max(size - int(m.group(2)), 0), size - 1
        if start > end: return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
        return StreamingResponse(storage.stream(key, start, end), status_code=206, media_type=media_type, headers=headers)
    headers["Content-Length"] = str(size)
    return StreamingResponse(storage.stream(key), media_type=media_type, headers=headers)

def kind_of(name: str) -> str:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    return {"pdf": "pdf", "pptx": "pptx", "docx": "docx", "txt": "text", "md": "text", "vtt": "text", "srt": "text",
            "png": "image", "jpg": "image", "jpeg": "image", "webp": "image"}.get(ext, "text")

# ---------------------------------------------------------------- app
from fastapi import Depends
import auth
from auth import current_user
from scripts.check_env import enforce as check_env
check_env()  # refuses to boot on ENV=production + AUTH=off or missing secrets
app = FastAPI(title="CognitioFlow")
auth.install(app, db)  # session middleware + /auth/* routes; everything else needs a signed-in user
init()

class CourseIn(BaseModel): name: str; accent: str = "#24467a"; tutor_prompt: str = ""
class NoteIn(BaseModel): title: str = "Untitled"; body: str = ""
class CardIn(BaseModel): front: str; back: str; source: str = ""; week: str = ""
class ReviewIn(BaseModel): rating: int  # 0 again, 1 hard, 2 good, 3 easy
class SessionIn(BaseModel): day: str; topic: str; minutes: int = 60
class ChatIn(BaseModel): message: str; mode: str = "drill"; model: Optional[str] = None  # model="auto" or explicit
class GenIn(BaseModel): file_id: Optional[str] = None; count: int = 8; model: Optional[str] = None

def rows(q, *a):
    with db() as c:
        return list(c.execute(q, a).fetchall())

@app.get("/")
def index(): return FileResponse(ROOT / "static" / "index.html")

@app.get("/healthz")
def healthz(): return {"ok": True}

@app.get("/api/config")
def config(user: dict = Depends(current_user)): return {"email": user["email"], "model": MODEL, "cheap_model": CHEAP_MODEL, "strong_model": STRONG_MODEL, "models": MODELS,
                      "has_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}

# courses
@app.get("/api/courses")
def courses(): return rows("SELECT * FROM courses ORDER BY created")

@app.post("/api/courses")
def add_course(c: CourseIn, user: dict = Depends(current_user)):
    cid = uuid.uuid4().hex[:8]
    with db() as d: d.execute("INSERT INTO courses(id,name,accent,tutor_prompt,created,user_id) VALUES(?,?,?,?,?,?)", (cid, c.name, c.accent, c.tutor_prompt, time.time(), user["id"]))
    return {"id": cid}

@app.put("/api/courses/{cid}")
def edit_course(cid: str, c: CourseIn):
    with db() as d: d.execute("UPDATE courses SET name=?,accent=?,tutor_prompt=? WHERE id=?", (c.name, c.accent, c.tutor_prompt, cid))
    return {"ok": True}

# files
@app.get("/api/courses/{cid}/files")
def files(cid: str):
    return rows("SELECT id,name,kind,chars,selected,status,week,created FROM files WHERE course_id=? ORDER BY created DESC", cid)

@app.post("/api/courses/{cid}/files")
async def upload(cid: str, file: UploadFile = File(...), week: str = Form("")):
    fid = uuid.uuid4().hex; kind = kind_of(file.filename)
    data = await file.read()
    text = "" if kind == "image" else extract_bytes(data, file.filename, kind)
    key = f"courses/{cid}/files/{fid}/{storage.safe_name(file.filename)}"
    storage.put(key, data, file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream")
    status = "image" if kind == "image" else ("indexed" if text.strip() and not text.startswith("[extraction failed") else "no text")
    with db() as d:
        d.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (fid, cid, file.filename, kind, key, text, len(text), 1, status, week, time.time()))
    return {"id": fid, "status": status, "chars": len(text)}

@app.post("/api/files/{fid}/toggle")
def toggle(fid: str):
    with db() as d: d.execute("UPDATE files SET selected=1-selected WHERE id=?", (fid,))
    return {"ok": True}

class ToggleToIn(BaseModel): on: bool

@app.post("/api/files/{fid}/toggle-to")
def toggle_to(fid: str, t: ToggleToIn):
    """Set a file's tick explicitly — the week header's tick-all sends the same state to every file in the group."""
    if not rows("SELECT 1 FROM files WHERE id=?", fid): raise HTTPException(404)
    with db() as d: d.execute("UPDATE files SET selected=? WHERE id=?", (1 if t.on else 0, fid))
    return {"ok": True, "selected": 1 if t.on else 0}

_WEEK_IN_NAME = re.compile(r"(?i)(?:^|[^a-z0-9])(?:w|wk|week|lecture|lec)[\s._-]*0?(\d{1,2})(?!\d)")

@app.post("/api/courses/{cid}/infer-weeks")
def infer_weeks(cid: str):
    """Tag untagged files with a week: from the filename when it says so (free), otherwise one cheap-model call over the rest."""
    untagged = rows("SELECT id,name,kind,text FROM files WHERE course_id=? AND COALESCE(week,'')=''", cid)
    found, rest = {}, []
    for f in untagged:
        m = _WEEK_IN_NAME.search(f["name"])
        if m and 1 <= int(m.group(1)) <= 20: found[f["id"]] = str(int(m.group(1)))
        elif f["kind"] != "image" and (f["text"] or "").strip(): rest.append(f)
    names = {f["id"]: f["name"] for f in untagged}
    def save(tags):
        with db() as d:
            for fid, wk in tags.items():
                d.execute("UPDATE files SET week=? WHERE id=? AND COALESCE(week,'')=''", (wk, fid))
                d.execute("UPDATE cards SET week=? WHERE course_id=? AND source=? AND COALESCE(week,'')=''", (wk, cid, names[fid]))  # cards made from it follow
    save(found)  # filename matches are free and certain: keep them even if the model step fails
    by_name, by_model, warning = len(found), {}, ""
    if rest:
        batch = rest[:25]; ids = {f["id"] for f in batch}
        known = rows("SELECT name,week FROM files WHERE course_id=? AND COALESCE(week,'')<>'' ORDER BY week LIMIT 80", cid)
        hint = "\n".join(f"- week {k['week']}: {k['name']}" for k in known) or "(no files tagged yet)"
        docs = "\n\n".join(f'<file id="{f["id"]}" name="{f["name"]}">\n{(f["text"] or "")[:3000]}\n</file>' for f in batch)
        prompt = ("Assign each untagged course file to a teaching week, using what it covers, dates, lecture numbers or headings, and the files already tagged. "
                  "Only give a week when the file itself gives real evidence; otherwise use an empty string. Weeks are whole numbers from 1 to 20.\n"
                  'Return ONLY a JSON object mapping file id to week, e.g. {"abc": "3", "def": ""}.\n\n'
                  f"FILES ALREADY TAGGED:\n{hint}\n\nUNTAGGED FILES:\n{docs}")
        try:
            got = _model_json(client().messages.create(model=CHEAP_MODEL, max_tokens=1000, messages=[{"role": "user", "content": prompt}]))
        except Exception as e:  # no API key, API error, or a reply that isn't JSON
            got = {}
            warning = (e.detail if isinstance(e, HTTPException) else "The model step failed") + " — files named with a week were still sorted."
        for fid, wk in (got.items() if isinstance(got, dict) else []):
            wk = str(wk).strip()
            if fid in ids and wk.isdigit() and 1 <= int(wk) <= 20: by_model[fid] = str(int(wk))
        save(by_model)
    out = {"tagged": by_name + len(by_model), "by_name": by_name, "by_model": len(by_model)}
    if warning: out["warning"] = warning
    return out

@app.delete("/api/files/{fid}")
def delete_file(fid: str):
    with db() as d:
        r = d.execute("SELECT key FROM files WHERE id=?", (fid,)).fetchone()
        if r and r["key"]: storage.delete(r["key"])
        d.execute("DELETE FROM files WHERE id=?", (fid,))
    return {"ok": True}

@app.get("/api/files/{fid}/text")
def file_text(fid: str):
    r = rows("SELECT name,text FROM files WHERE id=?", fid)
    if not r: raise HTTPException(404)
    return r[0]

@app.get("/api/files/{fid}/raw")
def file_raw(fid: str, request: Request):
    r = rows("SELECT key,name FROM files WHERE id=?", fid)
    if not r: raise HTTPException(404)
    return serve_object(r[0]["key"], request, mimetypes.guess_type(r[0]["key"] or "")[0] or "application/octet-stream", filename=r[0]["name"])

# ---------------------------------------------------------------- tutor
def build_context(cid: str):
    """Selected files → text blocks (within budget) + image blocks."""
    fs = rows("SELECT * FROM files WHERE course_id=? AND selected=1 ORDER BY created", cid)
    text_parts, images, used = [], [], 0
    for f in fs:
        if f["kind"] == "image":
            if len(images) < MAX_IMAGES:
                try: raw = storage.get(f["key"])
                except storage.NotFound: continue
                mt = "image/png" if f["key"].lower().endswith(".png") else "image/jpeg"
                images.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(raw).decode()}})
            continue
        t = f["text"] or ""
        if not t.strip(): continue
        room = CONTEXT_CHAR_BUDGET - used
        if room <= 0: text_parts.append(f"[{f['name']} omitted — context budget reached]"); continue
        if len(t) > room: t = t[:room] + "\n[… truncated]"
        used += len(t)
        text_parts.append(f"<file name=\"{f['name']}\" week=\"{f['week']}\">\n{t}\n</file>")
    return text_parts, images

def client():
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"): raise HTTPException(400, "ANTHROPIC_API_KEY not set — add it to .env and restart.")
    return anthropic.Anthropic()

def _text(m) -> str:
    return "".join(b.text for b in m.content if getattr(b, "type", "") == "text")

_CUT = re.compile(r"<!--cf:continue ([^>]*)-->")

def _reply_text(m) -> str:
    """Model text, trimmed — except that a reply cut off at the cap keeps its trailing characters, so Continue can join exactly."""
    t = _text(m)
    return t.lstrip() if getattr(m, "stop_reason", "") == "max_tokens" else t.strip()

def _mark_if_cut(text: str, m, **meta) -> str:
    """Hidden marker when the model stopped at the token cap, so Continue knows how to finish this note.
    Values are URL-quoted: a free-text week like "Week 3" must survive the space-separated marker."""
    if getattr(m, "stop_reason", "") != "max_tokens": return text
    return text + "\n\n<!--cf:continue " + " ".join(f"{k}={quote(str(v), safe='')}" for k, v in meta.items() if v not in ("", None)) + "-->"

def _model_json(m):
    """Parse a JSON reply, tolerating code fences or a sentence around the JSON."""
    text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip().strip("`")
    if text.startswith("json"): text = text[4:]
    try: return json.loads(text)
    except Exception: pass
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]; end = max(text.rfind("]"), text.rfind("}"))
    if starts and end > min(starts):
        try: return json.loads(text[min(starts):end + 1])
        except Exception: pass
    raise HTTPException(502, "Model returned non-JSON; try again.")

# Which model each task deserves. Cheap for bulk/recall work, strong where correction quality matters.
ROUTE = {"drill": MODEL, "explain": MODEL, "notes": CHEAP_MODEL, "cards": CHEAP_MODEL, "summarise": CHEAP_MODEL}

def pick_model(mode: str, requested: Optional[str], text: str = "") -> str:
    if requested and requested in MODELS: return requested
    m = ROUTE.get(mode, MODEL)
    # Escalate cheap tasks when the ask is clearly analytical rather than mechanical.
    if m == CHEAP_MODEL and any(k in text.lower() for k in
        ("compare", "contrast", "irac", "why", "critique", "conflict", "diverge", "exam answer", "argue")):
        m = MODEL
    return m

NOTE_STYLE = """
HOUSE STYLE for notes (readability first):
- One idea per line. Short lines. Lead with the rule in **bold**, then the case in *italics* with its citation, then the tag.
- Numbered lists for tests and sequences; bullets for everything else; never a wall of prose.
- Start with a 3–5 line **In one glance** box (a > blockquote) saying what the topic is, the test, and the exam moves.
- Visualise wherever the structure is visual, using ```mermaid blocks:
  · a decision tree (flowchart TD) for any legal test with branches (scope → justification → proportionality);
  · a left-to-right chain (flowchart LR) for sequences of cases or a remedial ladder (e.g. Van Gend → Costa → Simmenthal);
  · a table for compare-and-contrast (two freedoms, two cases, two models).
  Keep node labels to 2–6 words. Use rectangular nodes [ ] only — no { } diamonds (they render huge); put the question in the label. Edge labels for the answers. No diagram for a single flat list.
- Call out traps as a > blockquote starting **Trap:**, and exam moves as > **Exam move:**.
- Provenance tag at the end of every substantive line: [WG] [LECTURE] [SLIDES] [SCHUTZE p.] [READER] [ADDED]; ?? for unverified.
"""

MODES = {
    "drill": "Mode: Socratic drill. Ask one question, wait, then correct firmly and specifically.",
    "explain": "Mode: explain. Give a tight, structured explanation with references to the files (file name, slide/page where visible).",
    "notes": "Mode: build notes. Reconcile the supplied files into master notes with provenance tags; flag conflicts and gaps.\n" + NOTE_STYLE,
}

@app.get("/api/courses/{cid}/messages")
def messages(cid: str): return rows("SELECT id,role,content,created FROM messages WHERE course_id=? ORDER BY created", cid)

@app.delete("/api/courses/{cid}/messages")
def clear_messages(cid: str):
    with db() as d: d.execute("DELETE FROM messages WHERE course_id=?", (cid,))
    return {"ok": True}

@app.post("/api/courses/{cid}/chat")
def chat(cid: str, body: ChatIn):
    course = rows("SELECT * FROM courses WHERE id=?", cid)
    if not course: raise HTTPException(404)
    course = course[0]
    text_parts, images = build_context(cid)
    system = [{"type": "text", "text": BASE_PROMPT + "\n" + (course["tutor_prompt"] or "") + "\n" + MODES.get(body.mode, MODES["drill"])}]
    if text_parts:
        system.append({"type": "text", "text": "COURSE FILES:\n" + "\n\n".join(text_parts), "cache_control": {"type": "ephemeral"}})
    else:
        system.append({"type": "text", "text": "COURSE FILES: none selected. Say so if the question needs them."})
    history = [{"role": m["role"], "content": m["content"]} for m in messages(cid)][-30:]
    user_content = images + [{"type": "text", "text": body.message}] if images else body.message
    with db() as d: d.execute("INSERT INTO messages VALUES(?,?,?,?,?)", (uuid.uuid4().hex, cid, "user", body.message, time.time()))

    def gen():
        out = []
        chosen = pick_model(body.mode, body.model, body.message)
        yield f"data: {json.dumps({'model': chosen})}\n\n"
        try:
            with client().messages.stream(model=chosen, max_tokens=2000, system=system,
                                          messages=history + [{"role": "user", "content": user_content}]) as s:
                for t in s.text_stream:
                    out.append(t); yield f"data: {json.dumps({'t': t})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        full = "".join(out)
        if full:
            with db() as d: d.execute("INSERT INTO messages VALUES(?,?,?,?,?)", (uuid.uuid4().hex, cid, "assistant", full, time.time()))
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

# ---------------------------------------------------------------- notes
@app.get("/api/courses/{cid}/notes")
def notes(cid: str): return rows("SELECT id,title,updated,length(body) AS chars FROM notes WHERE course_id=? ORDER BY updated DESC", cid)

@app.post("/api/courses/{cid}/notes")
def add_note(cid: str, n: NoteIn):
    nid = uuid.uuid4().hex[:10]
    with db() as d: d.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (nid, cid, n.title, n.body, time.time()))
    return {"id": nid}

@app.get("/api/notes/{nid}")
def note(nid: str):
    r = rows("SELECT * FROM notes WHERE id=?", nid)
    if not r: raise HTTPException(404)
    return r[0]

@app.put("/api/notes/{nid}")
def save_note(nid: str, n: NoteIn):
    with db() as d:
        cur = d.execute("SELECT title,body FROM notes WHERE id=?", (nid,)).fetchone()
        last = d.execute("SELECT created FROM note_versions WHERE note_id=? ORDER BY created DESC LIMIT 1", (nid,)).fetchone()
        # snapshot the outgoing text at most every 3 minutes, and only if it actually changed
        if cur and cur["body"] != n.body and cur["body"].strip() and (not last or time.time() - last["created"] > 180):
            d.execute("INSERT INTO note_versions VALUES(?,?,?,?,?)", (uuid.uuid4().hex, nid, cur["title"], cur["body"], time.time()))
        d.execute("UPDATE notes SET title=?,body=?,updated=? WHERE id=?", (n.title, n.body, time.time(), nid))
    return {"ok": True}

@app.get("/api/notes/{nid}/versions")
def versions(nid: str): return rows("SELECT id,title,created,length(body) AS chars FROM note_versions WHERE note_id=? ORDER BY created DESC", nid)

@app.get("/api/versions/{vid}")
def version(vid: str):
    v = rows("SELECT * FROM note_versions WHERE id=?", vid)
    if not v: raise HTTPException(404)
    return v[0]

@app.post("/api/notes/{nid}/restore/{vid}")
def restore(nid: str, vid: str):
    v = version(vid); cur = note(nid)
    with db() as d:
        d.execute("INSERT INTO note_versions VALUES(?,?,?,?,?)", (uuid.uuid4().hex, nid, cur["title"], cur["body"], time.time()))
        d.execute("UPDATE notes SET body=?,updated=? WHERE id=?", (v["body"], time.time(), nid))
    return {"ok": True}

@app.delete("/api/notes/{nid}")
def del_note(nid: str):
    with db() as d: d.execute("DELETE FROM notes WHERE id=?", (nid,))
    return {"ok": True}

@app.post("/api/notes/{nid}/to-file")
def note_to_file(nid: str):
    """Snapshot a note into the course files so the tutor can read it."""
    n = note(nid)
    fid = uuid.uuid4().hex; key = f"courses/{n['course_id']}/files/{fid}/{storage.safe_name(n['title'] + '.md')}"
    storage.put(key, n["body"].encode(), "text/markdown; charset=utf-8")
    with db() as d:
        d.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (fid, n["course_id"], f"Note: {n['title']}", "text", key, n["body"], len(n["body"]), 1, "indexed", "", time.time()))
    return {"id": fid}

# ---------------------------------------------------------------- cards (SM-2)
WEAK_EASE = 2.3  # SM-2 ease falls below this after one "Again" or two "Hard" ratings

def _card_scope(cid: str, due: int = 0, week: str = "", weak: int = 0):
    q, a = "SELECT * FROM cards WHERE course_id=?", [cid]
    if due: q += " AND (due IS NULL OR due<=?)"; a.append(date.today().isoformat())
    if week: q += " AND week=?"; a.append(week)
    if weak: q += " AND ease<?"; a.append(WEAK_EASE)
    return q, a

@app.get("/api/courses/{cid}/cards")
def cards(cid: str, due: int = 0, week: str = "", weak: int = 0):
    q, a = _card_scope(cid, due, week, weak)
    return rows(q + " ORDER BY due, created", *a)

@app.post("/api/courses/{cid}/cards")
def add_card(cid: str, c: CardIn):
    kid = uuid.uuid4().hex[:10]
    with db() as d: d.execute("INSERT INTO cards(id,course_id,front,back,source,week,due,created) VALUES(?,?,?,?,?,?,?,?)",
                              (kid, cid, c.front, c.back, c.source, c.week.strip(), date.today().isoformat(), time.time()))
    return {"id": kid}

@app.delete("/api/cards/{kid}")
def del_card(kid: str):
    with db() as d: d.execute("DELETE FROM cards WHERE id=?", (kid,))
    return {"ok": True}

@app.post("/api/cards/{kid}/review")
def review(kid: str, r: ReviewIn):
    c = rows("SELECT * FROM cards WHERE id=?", kid)
    if not c: raise HTTPException(404)
    c = c[0]; q = {0: 1, 1: 3, 2: 4, 3: 5}[max(0, min(3, r.rating))]
    ease, interval, reps = c["ease"], c["interval"], c["reps"]
    if q < 3: reps, interval = 0, 0
    else:
        interval = 1 if reps == 0 else (6 if reps == 1 else round(interval * ease))
        reps += 1
    ease = max(1.3, ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    due = (date.today() + timedelta(days=interval)).isoformat()
    with db() as d:
        d.execute("UPDATE cards SET ease=?,interval=?,reps=?,due=? WHERE id=?", (ease, interval, reps, due, kid))
        d.execute("INSERT INTO reviews VALUES(?,?,?,?)", (uuid.uuid4().hex, kid, r.rating, time.time()))
    return {"due": due, "interval": interval}

@app.post("/api/courses/{cid}/cards/generate")
def generate_cards(cid: str, g: GenIn):
    if g.file_id:
        f = rows("SELECT name,text,week FROM files WHERE id=?", g.file_id)
        if not f: raise HTTPException(404)
        src, week, txt = f[0]["name"], f[0]["week"] or "", (f[0]["text"] or "")[:60000]
    else:
        parts, _ = build_context(cid); src, week, txt = "selected files", "", "\n\n".join(parts)[:60000]
    prompt = (f"From the material below, write {g.count} flashcards for a law exam: precise, one testable point each, "
              "case names and article numbers where present. Return ONLY a JSON array of objects with keys 'front' and 'back'.\n\n" + txt)
    m = client().messages.create(model=pick_model('cards', g.model), max_tokens=3000, messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in m.content if b.type == "text").strip().strip("`")
    if text.startswith("json"): text = text[4:]
    try: items = json.loads(text)
    except Exception: raise HTTPException(500, "Model returned non-JSON; try again.")
    made = 0
    with db() as d:
        for it in items:
            if it.get("front") and it.get("back"):
                d.execute("INSERT INTO cards(id,course_id,front,back,source,week,due,created) VALUES(?,?,?,?,?,?,?,?)",
                          (uuid.uuid4().hex[:10], cid, it["front"], it["back"], src, week, date.today().isoformat(), time.time())); made += 1
    return {"made": made}


@app.get("/api/courses/{cid}/recall-map")
def recall_map(cid: str):
    """Week chips on Recall: due cards per week, whether the week has indexed files and cards, and the weak-card count."""
    weeks = {}
    def w(k):
        k = k or ""; return weeks.setdefault(k, {"week": k, "due": 0, "cards": 0, "indexed": 0, "ready": False})
    for f in rows("SELECT COALESCE(week,'') AS week, COUNT(*) AS n FROM files WHERE course_id=? AND status='indexed' GROUP BY COALESCE(week,'')", cid):
        w(f["week"])["indexed"] = f["n"]
    for c in rows("SELECT COALESCE(week,'') AS week, COUNT(*) AS n, SUM(CASE WHEN due IS NULL OR due<=? THEN 1 ELSE 0 END) AS due "
                  "FROM cards WHERE course_id=? GROUP BY COALESCE(week,'')", date.today().isoformat(), cid):
        x = w(c["week"]); x["cards"] = c["n"]; x["due"] = int(c["due"] or 0); x["ready"] = c["n"] > 0
    weak = rows("SELECT COUNT(*) AS n FROM cards WHERE course_id=? AND ease<?", cid, WEAK_EASE)[0]["n"]
    order = lambda x: (x["week"] == "", int(x["week"]) if x["week"].isdigit() else 999, x["week"])
    return {"weeks": sorted(weeks.values(), key=order), "weak": weak}

class QuizIn(BaseModel): count: int = 8; week: str = ""; weak: int = 0

@app.post("/api/courses/{cid}/quiz")
def quiz(cid: str, qz: QuizIn):
    """Multiple choice built from the course's own cards: the card's back is the right answer, the cheap model writes three wrong ones."""
    q, a = _card_scope(cid, 0, qz.week, qz.weak)
    picked = rows(q + " ORDER BY (CASE WHEN due IS NULL OR due<=? THEN 0 ELSE 1 END), ease, RANDOM() LIMIT ?",
                  *a, date.today().isoformat(), max(1, min(20, qz.count)))
    if not picked: return []
    ids = [c["id"] for c in picked]
    others = [c["back"][:200] for c in rows("SELECT id,back FROM cards WHERE course_id=? ORDER BY RANDOM() LIMIT 60", cid) if c["id"] not in ids]
    items = "\n".join(f"{i}. Q: {c['front']}\n   A: {c['back']}" for i, c in enumerate(picked))
    prompt = ("Write multiple-choice distractors for a law exam quiz. For each numbered question, give exactly three wrong answers: plausible to a student "
              "who half-knows the material, the same form and length as the right answer, clearly wrong on a careful reading, never a paraphrase of the "
              "right answer. Borrow names, articles and rules from the course's other cards where they fit.\n"
              'Return ONLY a JSON array of objects {"i": <question number>, "wrong": [three strings]}.\n\nQUESTIONS:\n' + items +
              "\n\nOTHER CARDS IN THIS COURSE (answers only):\n" + ("\n".join("- " + o for o in others) or "(none)"))
    got = _model_json(client().messages.create(model=CHEAP_MODEL, max_tokens=3000, messages=[{"role": "user", "content": prompt}]))
    wrong_by_i = {}
    for x in got if isinstance(got, list) else []:
        if not (isinstance(x, dict) and isinstance(x.get("wrong"), list)): continue  # a string here would be iterated letter by letter
        try: wrong_by_i[int(x["i"])] = x["wrong"]
        except Exception: continue
    out = []
    for i, c in enumerate(picked):
        right = c["back"].strip()
        wrong = list(dict.fromkeys(str(v).strip() for v in (wrong_by_i.get(i) or []) if str(v).strip() and str(v).strip() != right))[:3]
        if len(wrong) < 3: continue  # never show a question with fewer than four options
        opts = wrong + [c["back"]]; random.shuffle(opts)
        out.append({"id": c["id"], "question": c["front"], "options": opts, "correct": c["back"]})
    return out

# ---------------------------------------------------------------- search
@app.get("/api/courses/{cid}/search")
def search(cid: str, q: str, limit: int = 20):
    q = q.strip()
    if len(q) < 2: return []
    like = f"%{q}%"; out = []
    def snip(text, n=140):
        i = (text or "").lower().find(q.lower()); 
        if i < 0: return (text or "")[:n]
        s = max(0, i - 50); return ("…" if s else "") + text[s:s+n].replace("\n", " ") + "…"
    for n in rows("SELECT id,title,body FROM notes WHERE course_id=? AND (title LIKE ? OR body LIKE ?) ORDER BY updated DESC LIMIT ?", cid, like, like, limit):
        out.append({"kind": "note", "id": n["id"], "title": n["title"], "snippet": snip(n["body"])})
    for f in rows("SELECT id,name,text,week FROM files WHERE course_id=? AND (name LIKE ? OR text LIKE ?) ORDER BY created DESC LIMIT ?", cid, like, like, limit):
        out.append({"kind": "file", "id": f["id"], "title": f["name"], "snippet": snip(f["text"]), "week": f["week"]})
    for m in rows("SELECT id,role,content,created FROM messages WHERE course_id=? AND content LIKE ? ORDER BY created DESC LIMIT ?", cid, like, limit):
        out.append({"kind": "chat", "id": m["id"], "title": ("You: " if m["role"] == "user" else "Tutor: ") + m["content"][:60].replace("\n", " "), "snippet": snip(m["content"])})
    for c in rows("SELECT id,front,back FROM cards WHERE course_id=? AND (front LIKE ? OR back LIKE ?) LIMIT ?", cid, like, like, limit):
        out.append({"kind": "card", "id": c["id"], "title": c["front"], "snippet": snip(c["back"])})
    return out[:limit * 2]

# ---------------------------------------------------------------- case index (Progress screen)
_CITE = re.compile(r"\b(?:Case\s+)?(?:[CT]-\d{1,4}/\d{2}|\d{1,3}/\d{2})\b|\bECLI:[A-Z]{2}:[A-Z]+:\d{4}:\d+")

@app.get("/api/courses/{cid}/cases")
def case_index(cid: str):
    """Cases named in the course's notes: *italic* names (house style) and the Case column of case-map tables,
    with the first citation seen and every note that mentions them. No model."""
    found = {}
    def add(name, cite, n):
        name = re.sub(r"\s+", " ", name).strip(" *_.,;:")
        if not name or not name[0].isupper() or len(name) > 80 or len(name.split()) > 8: return
        c = found.setdefault(name.casefold(), {"name": name, "cite": "", "notes": []})
        if cite and not c["cite"]: c["cite"] = cite.strip()
        if all(x["id"] != n["id"] for x in c["notes"]): c["notes"].append({"id": n["id"], "title": n["title"]})
    for n in rows("SELECT id,title,body FROM notes WHERE course_id=? ORDER BY updated DESC", cid):
        body = n["body"] or ""; lines = body.splitlines()
        for i in range(len(lines) - 1):  # case-map tables first: they carry a proper citation column
            if not (lines[i].lstrip().startswith("|") and re.match(r"^\s*\|?\s*:?-+", lines[i + 1])): continue
            head = [h.strip().lower() for h in lines[i].strip().strip("|").split("|")]
            ci = next((k for k, h in enumerate(head) if "case" in h), None)
            if ci is None: continue
            cc = next((k for k, h in enumerate(head) if "citation" in h or h.startswith("cite")), None)
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                row = [c.strip() for c in lines[j].strip().strip("|").split("|")]; j += 1
                if len(row) == len(head) and row[ci]: add(row[ci], row[cc] if cc is not None else "", n)
        for m in re.finditer(r"(?<![*\w])\*(?![*\s])([^*\n]{1,80}?)(?<!\s)\*(?![*\w])", body):
            cm = _CITE.search(body[m.end():m.end() + 60])
            add(m.group(1), cm.group(0) if cm else "", n)
    return sorted(found.values(), key=lambda c: c["name"].casefold())

# ---------------------------------------------------------------- offline: recordings, cards from case map
@app.post("/api/notes/{nid}/recordings/start")
def rec_start(nid: str):
    rid = uuid.uuid4().hex[:10]
    with db() as d: d.execute("INSERT INTO recordings VALUES(?,?,?,?,0)", (rid, nid, "", time.time()))
    return {"id": rid, "started": time.time()}

@app.post("/api/recordings/{rid}/finish")
async def rec_finish(rid: str, audio: UploadFile = File(...), seconds: float = Form(0), auto: int = Form(1)):
    r = rows("SELECT note_id FROM recordings WHERE id=?", rid)
    if not r: raise HTTPException(404)
    key = f"notes/{r[0]['note_id']}/audio/{rid}.webm"; storage.put(key, await audio.read(), "audio/webm")
    with db() as d: d.execute("UPDATE recordings SET key=?, seconds=? WHERE id=?", (key, seconds, rid))
    started = False
    if auto:
        try: started = transcribe_start(rid)["status"] != "failed"
        except HTTPException: started = False  # e.g. STORAGE=local: the recording is still saved
    return {"id": rid, "seconds": seconds, "transcribing": started}

@app.get("/api/notes/{nid}/recordings")
def recs(nid: str, all: int = 0):
    if all: return rows("SELECT id,started,seconds FROM recordings WHERE note_id=? ORDER BY started", nid)
    return rows("SELECT id,started,seconds FROM recordings WHERE note_id=? AND key!='' ORDER BY started", nid)

@app.get("/api/recordings/{rid}/audio")
def rec_audio(rid: str, request: Request):
    p = rows("SELECT key FROM recordings WHERE id=?", rid)
    if not p or not p[0]["key"]: raise HTTPException(404)
    return serve_object(p[0]["key"], request, "audio/webm", expires_s=12 * 3600)  # long enough to scrub a lecture left open

@app.delete("/api/recordings/{rid}")
def rec_del(rid: str):
    p = rows("SELECT key FROM recordings WHERE id=?", rid)
    if p and p[0]["key"]: storage.delete(p[0]["key"])
    with db() as d: d.execute("DELETE FROM recordings WHERE id=?", (rid,))
    return {"ok": True}

@app.post("/api/notes/{nid}/cards-from-tables")
def cards_from_tables(nid: str):
    """Deterministic: every row of a Markdown table whose header has a Case column becomes a card. No model."""
    n = note(nid); lines = n["body"].splitlines(); made = 0; i = 0
    def cells(l): return [c.strip() for c in l.strip().strip("|").split("|")]
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1]):
            head = [h.lower() for h in cells(lines[i])]; i += 2
            ci = next((k for k, h in enumerate(head) if "case" in h), None)
            if ci is None: continue
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                row = cells(lines[i]); i += 1
                if len(row) != len(head) or not row[ci]: continue
                front = row[ci]; rest = [f"{head[k].capitalize()}: {row[k]}" for k in range(len(row)) if k != ci and row[k]]
                back = "\n".join(rest)
                if rows("SELECT 1 FROM cards WHERE course_id=? AND front=? AND source=?", n["course_id"], front, f"note:{nid}"): continue
                with db() as d: d.execute("INSERT INTO cards(id,course_id,front,back,source,due,created) VALUES(?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:10], n["course_id"], front, back, f"note:{nid}", date.today().isoformat(), time.time()))
                made += 1
        else: i += 1
    return {"made": made}

# ---------------------------------------------------------------- transcription jobs (Google Speech-to-Text; state in the jobs table)
STT_LANGS = {"en": "en-GB", "nl": "nl-NL", "de": "de-DE", "fr": "fr-FR"}
MAX_STT_ATTEMPTS = 3

def _latest_job(rid: str):
    j = rows("SELECT * FROM jobs WHERE ref_id=? AND kind='transcribe' ORDER BY created DESC LIMIT 1", rid)
    return j[0] if j else None

def _set_job(jid: str, **fields):
    fields["updated"] = time.time()
    sets = ", ".join(f"{k}=CAST(? AS jsonb)" if k in ("payload", "result") else f"{k}=?" for k in fields)
    vals = [json.dumps(v) if k in ("payload", "result") else v for k, v in fields.items()]
    with db() as d: d.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*vals, jid))

def _job_view(j):
    """The fields the UI already polls for, plus executor/attempts. 'submitted' and 'finishing' read as running."""
    if not j: return {"status": "none"}
    res = j["result"] or {}
    return {"id": j["id"], "status": {"submitted": "running", "finishing": "running"}.get(j["status"], j["status"]),
            "stage": "cleaning" if j["status"] == "finishing" else (j["stage"] or ""), "chars": res.get("chars"),
            "language": res.get("language"), "cleaned": res.get("cleaned"), "error": j["error"] or "",
            "executor": j["executor"], "attempts": j["attempts"]}

def _finish_transcription(job, segments, language):
    """Append the Live capture block (optionally cleaned) exactly as the laptop build did, then mark the job done.
    Returns True only for the call that did the work."""
    with db() as d:  # claim first, so two overlapping polls can never append the block twice
        claimed = d.execute("UPDATE jobs SET status='finishing', stage='cleaning', updated=? WHERE id=? AND status IN ('submitted','running') RETURNING id",
                            (time.time(), job["id"])).fetchone()
    if not claimed: return False
    try:
        rid, nid = job["ref_id"], job["payload"]["note_id"]
        text = stt.format_capture(segments or [], rid)
        stamp = time.strftime("%d %b %H:%M"); block = f"\n\n## Live capture — transcript {stamp}\n" + text
        cleaned = False
        if text and os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("CF_AUTO_CLEAN", "1") == "1":
            try:
                cid = rows("SELECT course_id FROM notes WHERE id=?", nid)[0]["course_id"]
                text = clean_text(cid, text); cleaned = True
                block = f"\n\n## Live capture — transcript {stamp} (cleaned)\n" + text
            except Exception as e: print("clean skipped:", e)
        with db() as d:
            body = d.execute("SELECT body FROM notes WHERE id=?", (nid,)).fetchone()["body"]
            d.execute("UPDATE notes SET body=?, updated=? WHERE id=?", (body.rstrip() + block, time.time(), nid))
        _set_job(job["id"], status="done", stage="", result={"chars": len(text), "language": language, "cleaned": cleaned})
        return True
    except Exception as e:
        _set_job(job["id"], status="failed", stage="", error=f"Could not add the transcript to the note: {e}")
        return False

@app.post("/api/recordings/{rid}/transcribe")
def transcribe_start(rid: str, lang: str = "en", retry: int = 0):
    """Send a recording to Google Speech-to-Text as a durable job and return at once; GET polls it to completion.
    A live job is returned as-is; a failed one is re-submitted (the Transcribe button or ?retry=1), at most 3 attempts."""
    r = rows("SELECT note_id, key FROM recordings WHERE id=?", rid)
    if not r or not r[0]["key"]: raise HTTPException(404)
    job = _latest_job(rid)
    if job and job["status"] != "failed": return _job_view(job)
    if job and job["attempts"] >= MAX_STT_ATTEMPTS:
        raise HTTPException(409, f"Transcription failed {job['attempts']} times — last error: {job['error']}")
    try: stt.check_ready()
    except stt.ProviderError as e: raise HTTPException(400, str(e))
    language = lang if "-" in lang else STT_LANGS.get(lang, "en-GB")
    if job:
        jid = job["id"]; _set_job(jid, status="queued", stage="", error="", attempts=job["attempts"] + 1)
    else:
        from psycopg import errors as pg_errors
        jid, now = uuid.uuid4().hex, time.time()
        try:
            with db() as d: d.execute("INSERT INTO jobs(id,kind,ref_id,status,executor,attempts,payload,created,updated) VALUES(?,?,?,?,?,?,CAST(? AS jsonb),?,?)",
                                      (jid, "transcribe", rid, "queued", "hosted", 1, json.dumps({"language": language}), now, now))
        except pg_errors.UniqueViolation:
            return _job_view(_latest_job(rid))  # a second click raced this one: return its job
    try:
        op = stt.submit(r[0]["key"], language)
        _set_job(jid, status="submitted", stage="submitted", payload={"op": op, "language": language, "note_id": r[0]["note_id"]})
    except Exception as e:
        _set_job(jid, status="failed", error=str(e) if isinstance(e, stt.ProviderError) else f"Could not submit: {type(e).__name__}: {e}")
    return _job_view(_latest_job(rid))

@app.get("/api/recordings/{rid}/transcribe")
def transcribe_status(rid: str):
    """Poll the provider for an unfinished job; when it is done, finish it in this request. A closed tab
    simply completes the next time the note is opened."""
    job, collected = _latest_job(rid), False
    # a finish that died mid-way is collected again; the window must outlast a long cleaning pass
    # (a 90-minute lecture is ~17 cheap-model chunks), or a live finish could be claimed twice
    if job and job["status"] == "finishing" and time.time() - (job["updated"] or 0) > 30 * 60:
        _set_job(job["id"], status="running"); job = _latest_job(rid)
    if job and job["status"] in ("submitted", "running"):
        try:
            state, segments, detail = stt.poll(job["payload"]["op"])
        except stt.ProviderError as e:
            _set_job(job["id"], status="failed", stage="", error=str(e))
        except Exception as e:  # transient (network, 5xx): leave the job alone; the next poll tries again
            print("transcription poll:", type(e).__name__, e)
        else:
            if state == "running" and job["status"] != "running": _set_job(job["id"], status="running", stage="transcribing")
            elif state == "failed": _set_job(job["id"], status="failed", stage="", error=detail or "Speech-to-Text failed.")
            elif state == "done": collected = _finish_transcription(job, segments, detail)
        job = _latest_job(rid)
    view = _job_view(job)
    if collected: view["collected"] = True  # this request added the block: the UI reloads the open note
    return view

# ---------------------------------------------------------------- de-garble a transcript (cheap model, glossary-constrained)
def _glossary(cid: str, limit: int = 220) -> list:
    """Case names, citations and terms harvested from the course's ticked files — the only vocabulary the cleaner may 'correct' towards."""
    text = "\n".join((f["text"] or "")[:60000] for f in rows("SELECT text FROM files WHERE course_id=? AND selected=1 AND kind!='image'", cid))
    found = set()
    for m in re.finditer(r"\b([A-Z][\w'’-]+(?:\s+(?:v|de|du|di|van|von|and|&)\s+[A-Z][\w'’-]+)+)", text): found.add(m.group(1))
    for m in re.finditer(r"\b(?:Case\s+)?(C-\d{1,3}/\d{2})\b", text): found.add(m.group(1))
    for m in re.finditer(r"\*([A-Z][^*\n]{3,40})\*", text): found.add(m.group(1).strip())
    KNOWN = {"eu": ("Dassonville", "Cassis de Dijon", "Keck", "Van Gend en Loos", "Costa v ENEL", "Simmenthal", "Francovich", "Brasserie du Pêcheur", "Factortame",
              "Humblot", "Outokumpu", "Statistical Levy", "Art Treasures", "Jägerskiöld", "Tobacco Advertising", "Titanium Dioxide", "Gebhard", "Bosman", "Lawrie-Blum",
              "TFEU", "TEU", "MEQR", "Article 30", "Article 34", "Article 35", "Article 36", "Article 110", "Article 114", "Article 45", "Schütze", "Villanueva"),
             "prop": ("DCFR", "VIII.–2:101", "VIII.–3:101", "VIII.–4:101", "VIII.–5:202", "VIII.–5:203", "Art. 3:84 DCC", "§ 929 BGB", "Art. 1196 CC",
              "numerus clausus", "Typenzwang", "Typenfixierung", "erga omnes", "inter partes", "nemo dat quod non habet", "nemo plus", "prior tempore", "droit de suite",
              "specificatio", "solo consensu", "Sicherungsübereignung", "Verstijlen", "Hoops", "van der Linden", "Zimmermann", "Hasnaoui",
              "Re Goldcorp", "Armory v Delamirie", "Noorlander v Ligtvoet", "Pye v United Kingdom", "Modelboard", "retention of ownership", "commingling", "combination")}
    for w in KNOWN.get(cid, ()): found.add(w)
    return sorted(found, key=len, reverse=True)[:limit]

def clean_text(cid: str, text: str) -> str:
    gl = _glossary(cid)
    system = ("You repair automatic speech-to-text of an EU law lecture. Fix ONLY mis-heard words: case names, articles, Latin/French terms, numbers, the lecturer's name — "
              "using this glossary as the vocabulary to correct towards:\n" + ", ".join(gl) +
              "\nRules: keep every line, every leading [mm:ss] timestamp and every <!--...--> marker exactly as they are, in the same order. Do not summarise, reorder, add, or remove sentences. "
              "Do not change meaning or 'improve' grammar beyond what the mis-hearing requires. If unsure what a garbled word was, leave it and append (?) after it. Output the corrected text only.")
    lines = text.splitlines(); out = []; chunk = 70
    for i in range(0, len(lines), chunk):
        piece = "\n".join(lines[i:i + chunk])
        m = client().messages.create(model=CHEAP_MODEL, max_tokens=4000, system=system, messages=[{"role": "user", "content": piece}])
        got = "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip("\n")
        out.append(got if got.count("\n") >= piece.count("\n") - 3 else piece)   # refuse a chunk that lost lines
    return "\n".join(out)

@app.post("/api/notes/{nid}/clean-capture")
def clean_capture(nid: str):
    """Runs the cleaner over every Live capture section of a note. Original kept in History."""
    n = note(nid); body = n["body"]
    parts = re.split(r"(?m)(^##\s+Live capture[^\n]*\n)", body)
    if len(parts) < 3: raise HTTPException(400, "No Live capture section to clean.")
    with db() as d: d.execute("INSERT INTO note_versions VALUES(?,?,?,?,?)", (uuid.uuid4().hex, nid, n["title"], body, time.time()))
    rebuilt = parts[0]; changed = 0
    for k in range(1, len(parts), 2):
        head, sec = parts[k], parts[k + 1]
        cleaned = clean_text(n["course_id"], sec)
        if cleaned != sec: changed += 1
        rebuilt += head + cleaned
    with db() as d: d.execute("UPDATE notes SET body=?, updated=? WHERE id=?", (rebuilt, time.time(), nid))
    return {"sections": (len(parts) - 1) // 2, "changed": changed}

# ---------------------------------------------------------------- reconcile a note against its lecture capture
def _reconcile_inputs(n):
    """(system, prompt) for a reconcile — also used to continue one that stopped at the cap."""
    body = n["body"]
    course = rows("SELECT * FROM courses WHERE id=?", n["course_id"])[0]
    parts = re.split(r"(?m)^##\s+Live capture[^\n]*\n", body)
    base = parts[0].strip(); capture = "\n\n".join(p.strip() for p in parts[1:]).strip()
    if not capture: raise HTTPException(400, "No 'Live capture' section in this note — press + Lecture capture, type what was said, then reconcile.")
    fs = rows("SELECT name,text FROM files WHERE course_id=? AND selected=1 AND kind!='image'", n["course_id"])
    budget = CONTEXT_CHAR_BUDGET // 2; ctx = []
    for f in fs:
        t = (f["text"] or "")[:budget]; budget -= len(t); ctx.append(f"=== {f['name']} ===\n{t}")
        if budget <= 0: break
    system = BASE_PROMPT + "\n" + (course["tutor_prompt"] or "") + """
Mode: reconcile. """ + NOTE_STYLE + """You receive BASE NOTES (drafted from files) and a LIVE CAPTURE typed during the lecture. Authority: what the lecturer said outranks slides and textbook; annotated WG notes still outrank both. Lines tagged [!] are lecturer corrections and MUST override the base. [P] gives pinpoints to insert. ?? marks things the student missed — try to fill them from the files and tag [SLIDES]/[SCHUTZE]; if the files don't settle it, leave ?? in.
Output Markdown only, no preamble: the FULL corrected notes in the same structure as the base (keep headings, case-map table, any ```mermaid diagram — update the diagram if a rule changed). Tag every changed or added line [LECTURE] plus the original source tag if still valid. Never invent content that is in neither the capture nor the files.
End with:
## Reconciliation log
- one bullet per change: what the base said → what the lecturer said, and why it changed
## Still to verify
- remaining ?? items and any base/lecture conflict you could not settle
## Bottom line
- two to four lines, last: the corrections that matter most for the exam and what to fix first"""
    prompt = f"BASE NOTES:\n{base}\n\nLIVE CAPTURE:\n{capture}\n\nFILES (for pinpoints and filling gaps):\n" + "\n\n".join(ctx)
    return system, prompt

@app.post("/api/notes/{nid}/reconcile")
def reconcile_note(nid: str):
    """Split the note into base notes + 'Live capture' sections; rewrite the base so the capture outranks it. Saves a new note, keeps the original."""
    n = note(nid)
    system, prompt = _reconcile_inputs(n)
    m = client().messages.create(model=STRONG_MODEL, max_tokens=RECONCILE_TOKENS, system=system, messages=[{"role": "user", "content": prompt}])
    out = _reply_text(m)
    if not out.strip(): raise HTTPException(502, "Empty reply from the model.")
    out = _mark_if_cut(out, m, kind="reconcile", src=nid)
    new_id = uuid.uuid4().hex; title = re.sub(r"\s*\(reconciled.*\)$", "", n["title"]) + f" (reconciled {time.strftime('%d %b')})"
    with db() as d: d.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (new_id, n["course_id"], title, out, time.time()))
    return {"id": new_id, "title": title, "chars": len(out), "model": m.model}

# ---------------------------------------------------------------- auto-notes and auto-plan
class DraftIn(BaseModel): file_ids: list[str] = []; week: str = ""; title: str = ""; diagrams: bool = True

def _files_for(cid: str, file_ids: list, week: str):
    if file_ids:
        q = ",".join("?" * len(file_ids)); return rows(f"SELECT * FROM files WHERE course_id=? AND id IN ({q})", cid, *file_ids)
    if week: return rows("SELECT * FROM files WHERE course_id=? AND week=? AND selected=1", cid, week)
    return rows("SELECT * FROM files WHERE course_id=? AND selected=1", cid)

def _draft_inputs(cid: str, d: DraftIn):
    """(system, prompt, files) for a draft — also used to continue one that stopped at the cap."""
    course = rows("SELECT * FROM courses WHERE id=?", cid)
    if not course: raise HTTPException(404)
    fs = [f for f in _files_for(cid, d.file_ids, d.week) if f["text"]]
    if not fs: raise HTTPException(400, "No text files selected — tick files in Files or pass a week.")
    budget = CONTEXT_CHAR_BUDGET; parts = []
    for f in fs:
        t = f["text"][:budget]; budget -= len(t); parts.append(f"=== {f['name']} ===\n{t}")
        if budget <= 0: break
    system = BASE_PROMPT + "\n" + (course[0]["tutor_prompt"] or "") + """
Mode: build master notes. """ + NOTE_STYLE + """Output Markdown only, no preamble. Structure:
# <title>
## Scope (what this covers, which week/lecture)
## Core rules (numbered; each line ends with a provenance tag and pinpoint where visible: [WG] [SLIDES] [SCHUTZE] [LECTURE])
## Case map (table: Case · Citation · Rule · Exam move · Source)
## Traps and confusions (bullet list)
## Gaps / verify (things the files do not settle)
""" + ("""After the Core rules, add a ```mermaid flowchart (TD) of the main legal test as a decision tree — short node labels, the exam moves as branches. Add a second small diagram only if the material has a genuinely separate test. """ if d.diagrams else "") + """
Never import material that is not in the files. Where sources disagree, keep both and tag which outranks (WG > slides > textbook)."""
    scope = f"week {d.week}" if d.week else "all ticked files"
    prompt = (f"Draft {'week-' + d.week if d.week else 'master'} notes titled '{d.title or ('Week ' + d.week + ' notes' if d.week else 'Master notes')}' covering {scope}, from these files only:\n\n" + "\n\n".join(parts))
    return system, prompt, fs

@app.post("/api/courses/{cid}/notes/draft")
def draft_notes(cid: str, d: DraftIn):
    """Build a master-notes draft from selected files (or the ticked files of a week). Cheap model; escalates on size."""
    system, prompt, fs = _draft_inputs(cid, d)
    m = client().messages.create(model=pick_model("notes", None, ""), max_tokens=DRAFT_TOKENS, system=system,
                                 messages=[{"role": "user", "content": prompt}])
    body = _mark_if_cut(_reply_text(m), m, kind="draft", week=d.week, diagrams="1" if d.diagrams else "0",
                        files=",".join(f["id"] for f in fs))  # the files actually used, so Continue reads the same material if ticks change
    title = d.title or (body.splitlines()[0].lstrip("# ").strip() if body.startswith("#") else (f"Week {d.week} notes" if d.week else "Master notes"))
    nid = uuid.uuid4().hex
    with db() as c: c.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (nid, cid, title, body, time.time()))
    return {"id": nid, "title": title, "chars": len(body), "files": [f["name"] for f in fs], "model": m.model}

@app.post("/api/notes/{nid}/continue")
def continue_note(nid: str):
    """Finish a note the model left unfinished at the token cap. Current models reject an assistant prefill,
    so the partial text goes back in the user turn and the reply is appended."""
    n = note(nid); body = n["body"] or ""
    mk = _CUT.search(body)
    if not mk: raise HTTPException(400, "This note wasn't cut off — nothing to continue.")
    meta = {k: unquote(v) for k, v in (kv.split("=", 1) for kv in mk.group(1).split() if "=" in kv)}
    before = body[:mk.start()]
    partial = (before[:-2] if before.endswith("\n\n") else before) + body[mk.end():]  # drop only the separator the marker added
    if meta.get("kind") == "reconcile":
        src = rows("SELECT * FROM notes WHERE id=?", meta.get("src", ""))
        if not src: raise HTTPException(400, "The note this was reconciled from is gone — reconcile again from the original.")
        system, prompt = _reconcile_inputs(src[0]); model, cap = STRONG_MODEL, RECONCILE_TOKENS
    elif meta.get("kind") == "draft":
        d = DraftIn(week=meta.get("week", ""), diagrams=meta.get("diagrams", "1") == "1",
                    file_ids=[x for x in meta.get("files", "").split(",") if x])
        system, prompt, _ = _draft_inputs(n["course_id"], d); model, cap = pick_model("notes", None, ""), DRAFT_TOKENS
    else: raise HTTPException(400, "This note has no continuation marker the app understands.")
    ask = (prompt + "\n\nYou already wrote the answer below, but it was cut off at the token limit. Continue from exactly where it stops: "
           "no preamble, no repetition, no restating earlier sections — pick up mid-sentence if that is where it ends — and finish the sections still missing. "
           "Your reply is appended to the answer with nothing added in between, so begin with the exact next characters: the rest of the word if it stops "
           "mid-word, a space if a new word follows, a line break if a new line follows.\n\n"
           "ANSWER SO FAR:\n" + partial[-12000:])
    m = client().messages.create(model=model, max_tokens=cap, system=system, messages=[{"role": "user", "content": ask}])
    raw = _text(m)
    if not raw.strip(): raise HTTPException(502, "Empty reply from the model.")
    rest = raw if getattr(m, "stop_reason", "") == "max_tokens" else raw.rstrip()  # leading space or line break is the join itself
    joined = _mark_if_cut(partial + rest, m, **meta)
    with db() as c:
        c.execute("INSERT INTO note_versions VALUES(?,?,?,?,?)", (uuid.uuid4().hex, nid, n["title"], body, time.time()))
        c.execute("UPDATE notes SET body=?, updated=? WHERE id=?", (joined, time.time(), nid))
    return {"chars": len(joined), "added": len(rest), "cut": bool(_CUT.search(joined)), "model": m.model}

class PlanIn(BaseModel): start: str = ""; days: int = 7; minutes_per_day: int = 90; replace: bool = False

@app.post("/api/courses/{cid}/plan")
def auto_plan(cid: str, p: PlanIn):
    """Generate a study plan from the course planning files, what is indexed by week, and what is due for recall."""
    import datetime as dt
    course = rows("SELECT * FROM courses WHERE id=?", cid)
    if not course: raise HTTPException(404)
    start = p.start or dt.date.today().isoformat()
    planning = rows("SELECT name,text FROM files WHERE course_id=? AND (lower(name) LIKE '%plan%' OR lower(name) LIKE '%overview%' OR lower(name) LIKE '%exam%' OR lower(name) LIKE '%content%')", cid)
    by_week = rows("SELECT week, COUNT(*) AS n, string_agg(name, ' | ' ORDER BY name) AS names FROM files WHERE course_id=? GROUP BY week ORDER BY week", cid)
    notes_ = rows("SELECT title FROM notes WHERE course_id=?", cid)
    due = rows("SELECT COUNT(*) AS n FROM cards WHERE course_id=? AND due<=?", cid, date.today().isoformat())[0]["n"]
    existing = rows("SELECT day,topic,minutes,done FROM sessions WHERE course_id=? AND day>=? ORDER BY day", cid, start)
    ctx = "\n\n".join(f"=== {f['name']} ===\n{f['text'][:6000]}" for f in planning)
    state = {"today": start, "days_to_plan": p.days, "minutes_per_day": p.minutes_per_day,
             "files_by_week": [dict(r) for r in by_week], "notes": [n["title"] for n in notes_],
             "cards_due_now": due, "already_planned": [dict(r) for r in existing]}
    system = ("You plan study sessions for a law student. Output ONLY a JSON array, no prose, no code fence. Each item: "
              '{"day":"YYYY-MM-DD","topic":"<specific, e.g. Drill Art 34 scope: Dassonville→Cassis→Keck>","minutes":<int>}. '
              "Rules: respect the course calendar in the files (lecture days get a 30-min pre-read the day before and a 45-min reconcile the day after); "
              "spread recall (cards due) into short 15–20 min slots; never exceed minutes_per_day; do not duplicate already_planned; "
              "prefer material whose week matches the current point in the course; make topics concrete enough to act on.")
    m = client().messages.create(model=pick_model("summarise", None, ""), max_tokens=2000, system=system,
                                 messages=[{"role": "user", "content": f"COURSE PLANNING FILES:\n{ctx}\n\nSTATE:\n{json.dumps(state)}"}])
    text = "".join(b.text for b in m.content if getattr(b, "type", "") == "text").strip()
    text = text[text.find("["): text.rfind("]") + 1]
    try: items = json.loads(text)
    except Exception: raise HTTPException(502, "Planner returned something that was not JSON; try again.")
    added = 0
    with db() as c:
        if p.replace: c.execute("DELETE FROM sessions WHERE course_id=? AND day>=? AND done=0", (cid, start))
        for it in items:
            if not isinstance(it, dict) or not it.get("day") or not it.get("topic"): continue
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,0)", (uuid.uuid4().hex, cid, str(it["day"])[:10], str(it["topic"])[:160], int(it.get("minutes", 45)))); added += 1
    return {"added": added, "model": m.model}

# ---------------------------------------------------------------- planner + stats
@app.get("/api/sessions")
def sessions(): return rows("SELECT s.*,c.name AS course FROM sessions s JOIN courses c ON c.id=s.course_id ORDER BY day")

@app.post("/api/courses/{cid}/sessions")
def add_session(cid: str, s: SessionIn):
    sid = uuid.uuid4().hex[:8]
    with db() as d: d.execute("INSERT INTO sessions VALUES(?,?,?,?,?,0)", (sid, cid, s.day, s.topic, s.minutes))
    return {"id": sid}

class LogIn(BaseModel): minutes: int; topic: str = "Study session"

@app.post("/api/courses/{cid}/sessions/log")
def log_session(cid: str, s: LogIn):
    """The study timer: record time already spent as a done session today, so it counts in Progress."""
    sid = uuid.uuid4().hex; minutes = max(1, min(720, s.minutes))
    with db() as c: c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,1)", (sid, cid, date.today().isoformat(), (s.topic.strip() or "Study session")[:160], minutes))
    return {"id": sid, "minutes": minutes}

@app.post("/api/sessions/{sid}/toggle")
def toggle_session(sid: str):
    with db() as d: d.execute("UPDATE sessions SET done=1-done WHERE id=?", (sid,))
    return {"ok": True}

@app.delete("/api/sessions/{sid}")
def del_session(sid: str):
    with db() as d: d.execute("DELETE FROM sessions WHERE id=?", (sid,))
    return {"ok": True}

@app.get("/api/courses/{cid}/stats")
def stats(cid: str):
    today = date.today().isoformat()
    with db() as d:
        total    = d.execute("SELECT COUNT(*) AS n FROM cards WHERE course_id=?", (cid,)).fetchone()["n"]
        due      = d.execute("SELECT COUNT(*) AS n FROM cards WHERE course_id=? AND due<=?", (cid, today)).fetchone()["n"]
        retained = d.execute("SELECT COUNT(*) AS n FROM cards WHERE course_id=? AND interval>=6", (cid,)).fetchone()["n"]
        reviews  = d.execute("SELECT r.rating,r.created FROM reviews r JOIN cards c ON c.id=r.card_id WHERE c.course_id=?", (cid,)).fetchall()
        files_n  = d.execute("SELECT COUNT(*) AS n, COALESCE(SUM(chars),0) AS total_chars FROM files WHERE course_id=?", (cid,)).fetchone()
        minutes  = d.execute("SELECT COALESCE(SUM(minutes),0) AS n FROM sessions WHERE course_id=? AND done=1", (cid,)).fetchone()["n"]
        msgs     = d.execute("SELECT COUNT(*) AS n FROM messages WHERE course_id=? AND role='user'", (cid,)).fetchone()["n"]
    days = sorted({date.fromtimestamp(r["created"]).isoformat() for r in reviews}, reverse=True)
    streak, d0 = 0, date.today()
    for dd in days:
        if dd == d0.isoformat(): streak += 1; d0 -= timedelta(days=1)
        else: break
    acc = round(100 * sum(1 for r in reviews if r["rating"] >= 2) / len(reviews)) if reviews else None
    return {"cards": total, "due": due, "retained": retained, "reviews": len(reviews), "recall_accuracy": acc,
            "streak": streak, "files": files_n["n"], "file_chars": files_n["total_chars"], "study_minutes": minutes, "questions_asked": msgs}

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


if __name__ == "__main__":
    import uvicorn
    print(f"\nCognitioFlow → http://localhost:8000   (model: {MODEL}, key set: {bool(os.environ.get('ANTHROPIC_API_KEY'))})\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
