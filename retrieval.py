"""
Course-first retrieval (Phase 10).

The user's own materials are supreme: this module only ever ranks passages that are already in the course's ticked files
and notes. It never adds outside text, never widens the selection, and never drops a ticked file silently — the caller is
told which files were trimmed so the Reading strip can say so.

  chunk(text, ...)                     -> passages with headings and offsets
  authority(kind, name)                -> weight (annotated WG notes > lecture > slides > reader)
  rank(hits, budget_chars, files)      -> passages to send + files trimmed, one passage from every ticked file first
  index_source(db, ...)                -> replace one file's or note's passages
  search(rows, course_id, query, ...)  -> nearest passages, restricted to the sources given

The database is reached only through the db()/rows() callables the caller passes in, so this module never opens a
connection of its own (CLAUDE.md: db() and rows() are the only way to touch the database).
"""
import uuid
import re
from typing import List

TARGET = 1000          # characters per passage: a readable chunk, ~250 tokens
OVERLAP = 150          # carried between passages so a rule split across a boundary is still whole somewhere
MIN_TAIL = 300         # a trailing scrap shorter than this joins the previous passage

# Authority hierarchy from CLAUDE.md, applied as a multiplier on similarity. The steps are wide on purpose: the user's
# own annotated notes must win a close contest against a slide, not merely nudge it — their materials are supreme.
# Most specific first: "Lecture 1A slides" is slides, not a transcript.
AUTHORITY = (
    (re.compile(r"\bWG\b|working group|annotated", re.I), 2.00),   # annotated working-group notes
    (re.compile(r"slide|deck|\.pptx\b", re.I), 1.20),
    (re.compile(r"lecture|transcript|capture|live capture", re.I), 1.60),
    (re.compile(r"sch(ü|u)tze|reader|textbook|chapter", re.I), 1.00),
)
NOTE_BONUS = 1.50      # the user's own notes outrank slides and readings


def authority(kind: str, name: str = "", source: str = "file") -> float:
    """How much this material's own standing counts, before similarity."""
    hay = f"{name} {kind}"
    weight = next((w for pattern, w in AUTHORITY if pattern.search(hay)), 1.0)
    if source == "note":
        weight = max(weight, NOTE_BONUS)
    return weight


def _headings(text: str):
    """Markdown headings with their positions, so every passage can name where it came from."""
    return [(m.start(), m.group(2).strip()) for m in re.finditer(r"(?m)^(#{1,4})\s+(.+)$", text)]


def chunk(text: str, target: int = TARGET, overlap: int = OVERLAP) -> List[dict]:
    """Split on paragraph boundaries into ~target-character passages, keeping the nearest heading and start offset."""
    text = (text or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    heads = _headings(text)
    passages, start = [], 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind("\n#"), window.rfind(". "))
            if cut > target * 0.4:
                end = start + cut + 1
        if len(text) - end < MIN_TAIL:
            end = len(text)
        body = text[start:end].strip()
        if body:
            heading = next((h for pos, h in reversed(heads) if pos <= start), "")
            passages.append({"ord": len(passages), "start_char": start, "heading": heading, "text": body})
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return passages


def rank(hits: List[dict], budget_chars: int, ticked: List[dict]) -> dict:
    """Choose what to send.

    hits: {source_id, name, kind, source, text, score (cosine 0–1), ...} best-first from the database.
    ticked: every selected file/note, so each one is represented and nothing vanishes without a word.
    Returns {passages, files_used, files_trimmed, chars}.
    """
    for h in hits:
        h["weighted"] = h.get("score", 0) * authority(h.get("kind", ""), h.get("name", ""), h.get("source", "file"))
    ordered = sorted(hits, key=lambda h: h["weighted"], reverse=True)

    chosen, used, seen = [], 0, set()
    for source in ticked:                      # one passage from every ticked source first: nothing is invisible
        best = next((h for h in ordered if h["source_id"] == source["id"]), None)
        if best and used + len(best["text"]) <= budget_chars:
            chosen.append(best); used += len(best["text"]); seen.add(id(best))
    for h in ordered:                          # then the strongest passages overall
        if id(h) in seen or used + len(h["text"]) > budget_chars:
            continue
        chosen.append(h); used += len(h["text"]); seen.add(id(h))

    # Authority first (the user's own annotated notes lead), then reading order inside each source, so quotes stay traceable.
    chosen.sort(key=lambda h: (-authority(h.get("kind", ""), h.get("name", ""), h.get("source", "file")), h["name"], h.get("ord", 0)))
    used_ids = {h["source_id"] for h in chosen}
    return {
        "passages": chosen,
        "files_used": [s["name"] for s in ticked if s["id"] in used_ids],
        "files_trimmed": [s["name"] for s in ticked if s["id"] not in used_ids],
        "chars": used,
    }


# ---------------------------------------------------------------- the database side (accessors are injected)

def index_source(db, embed_texts, *, course_id: str, source: str, source_id: str, name: str, kind: str,
                 week: str, text: str, updated: float) -> int:
    """Replace this file's or note's passages with fresh ones. Returns how many were written."""
    passages = chunk(text)
    with db() as d:
        d.execute("DELETE FROM chunks WHERE source=? AND source_id=?", (source, source_id))
        if not passages:
            return 0
        vectors = embed_texts([p["text"] for p in passages])
        for p, vector in zip(passages, vectors):
            d.execute(
                "INSERT INTO chunks(id, course_id, source, source_id, name, kind, week, heading, ord, start_char, text, embedding, updated) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, course_id, source, source_id, name, kind, week, p["heading"], p["ord"],
                 p["start_char"], p["text"], _vector_literal(vector), updated))
    return len(passages)


def forget_source(db, source: str, source_id: str) -> None:
    with db() as d:
        d.execute("DELETE FROM chunks WHERE source=? AND source_id=?", (source, source_id))


def _vector_literal(vector) -> str:
    """pgvector accepts '[0.1,0.2,…]' as text; keeps psycopg free of an extra adapter."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vector) + "]"


def search(rows, embed_texts, *, course_id: str, query: str, source_ids: list, limit: int = 40) -> list:
    """Nearest passages from the given sources only — the ticked files stay the filter, never widened here."""
    if not source_ids or not (query or "").strip():
        return []
    vector = _vector_literal(embed_texts([query])[0])
    placeholders = ",".join("?" for _ in source_ids)
    found = rows(
        f"SELECT id, source, source_id, name, kind, week, heading, ord, start_char, text, "
        f"1 - (embedding <=> CAST(? AS vector)) AS score "
        f"FROM chunks WHERE course_id=? AND source_id IN ({placeholders}) AND embedding IS NOT NULL "
        f"ORDER BY embedding <=> CAST(? AS vector) LIMIT ?",
        vector, course_id, *source_ids, vector, limit)
    return [dict(r) for r in found]
