"""Phase 10: chunking, the authority order, the 'every ticked file gets a seat' rule, and a real save-then-search."""
import os
import uuid

import psycopg
import pytest

import retrieval

WG = {"id": "f1", "name": "W1 WG complete notes (annotated).pdf", "kind": "pdf"}
SLIDES = {"id": "f2", "name": "W1 Lecture 1A slides.txt", "kind": "text"}
READER = {"id": "f3", "name": "Schütze chapter 14.pdf", "kind": "pdf"}


def hit(source, text, score, ord_=0):
    return {"source_id": source["id"], "name": source["name"], "kind": source["kind"], "source": "file",
            "text": text, "score": score, "ord": ord_}


def test_chunking_keeps_headings_offsets_and_overlap():
    text = "# Free movement of goods\n\n" + ("Dassonville applies broadly. " * 60) + "\n\n## Cassis\n\n" + ("Mandatory requirements. " * 60)
    passages = retrieval.chunk(text)
    assert len(passages) >= 2
    assert passages[0]["heading"] == "Free movement of goods"
    assert any(p["heading"] == "Cassis" for p in passages)
    assert all(p["text"].strip() for p in passages)
    assert passages[1]["start_char"] < passages[0]["start_char"] + len(passages[0]["text"])  # passages overlap
    assert text[passages[1]["start_char"]:].startswith(passages[1]["text"][:20])             # offsets point at the source
    assert retrieval.chunk("   ") == []


def test_a_lecture_slide_deck_is_ranked_as_slides_not_as_a_transcript():
    assert retrieval.authority("text", "W1 Lecture 1A slides.txt") < retrieval.authority("text", "W2 Lecture A transcript.txt")


def test_the_authority_hierarchy_decides_ties():
    order = sorted([WG, SLIDES, READER], key=lambda f: retrieval.authority(f["kind"], f["name"]), reverse=True)
    assert [f["id"] for f in order] == ["f1", "f2", "f3"]
    assert retrieval.authority("note", "Week 2 A Lecture Notes", source="note") > retrieval.authority("pdf", "Schütze chapter 14.pdf")


def test_weaker_similarity_in_wg_notes_beats_a_slide():
    """A close contest goes to the user's own annotated notes, not to a slide that matched a few more words."""
    out = retrieval.rank([hit(SLIDES, "slide text", 0.80), hit(WG, "wg text", 0.70)], budget_chars=10_000, ticked=[WG, SLIDES])
    assert [p["source_id"] for p in out["passages"]] == ["f1", "f2"]
    assert retrieval.authority("pdf", WG["name"]) >= retrieval.authority("text", SLIDES["name"]) * 1.5


def test_every_ticked_file_keeps_a_seat_and_trimming_is_named():
    hits = [hit(WG, "w" * 400, 0.9, 0), hit(WG, "x" * 400, 0.88, 1), hit(SLIDES, "y" * 400, 0.50, 0), hit(READER, "z" * 400, 0.10, 0)]
    out = retrieval.rank(hits, budget_chars=900, ticked=[WG, SLIDES, READER])
    assert {p["source_id"] for p in out["passages"]} == {"f1", "f2"}          # two fit
    assert out["files_used"] == [WG["name"], SLIDES["name"]]
    assert out["files_trimmed"] == [READER["name"]]                           # the third is named, never silently dropped
    assert out["chars"] <= 900


def test_passages_come_back_in_reading_order():
    out = retrieval.rank([hit(WG, "second", 0.9, 5), hit(WG, "first", 0.8, 1)], budget_chars=1000, ticked=[WG])
    assert [p["text"] for p in out["passages"]] == ["first", "second"]


# ---------------------------------------------------------------- against the real database

def _fake_embed(texts):
    """Deterministic stand-in for the model: counts a few words, so 'nearest' is meaningful without downloading anything."""
    words = ["dassonville", "cassis", "packaging", "worker", "vat"]
    out = []
    for t in texts:
        low = t.lower()
        v = [low.count(w) for w in words] + [len(low) / 1000]
        out.append((v + [0.0] * 384)[:384])
    return out


@pytest.fixture
def chunk_db(pg):
    def db():
        class Ctx:
            def __enter__(self_inner): return _Cur(pg)
            def __exit__(self_inner, *a):
                pg.commit(); return False
        return Ctx()
    def rows(q, *args):
        cur = _Cur(pg).execute(q, args)
        return cur.fetchall()
    yield db, rows
    pg.execute("DELETE FROM chunks"); pg.commit()


class _Cur:
    """The same '?' placeholders and dict rows run.py uses, so retrieval.py is written against one dialect."""
    def __init__(self, conn): self.conn = conn
    def execute(self, q, args=()):
        from psycopg.rows import dict_row
        self.cur = self.conn.cursor(row_factory=dict_row).execute(q.replace("%", "%%").replace("?", "%s"), args)
        return self
    def fetchall(self): return self.cur.fetchall()


def test_index_then_search_finds_the_right_passage(chunk_db):
    db, rows = chunk_db
    n = retrieval.index_source(db, _fake_embed, course_id="eu", source="file", source_id="f1",
                               name="W1 WG complete notes (annotated).pdf", kind="pdf", week="1",
                               text="# Goods\n\n" + ("Dassonville dassonville. " * 50) + "\n\n## VAT\n\nVat vat vat rules.",
                               updated=0.0)
    assert n >= 2
    found = retrieval.search(rows, _fake_embed, course_id="eu", query="vat vat vat", source_ids=["f1"], limit=5)
    assert found and "Vat" in found[0]["text"]
    assert 0 <= found[0]["score"] <= 1


def test_reindexing_replaces_and_unticked_sources_are_not_searched(chunk_db):
    db, rows = chunk_db
    for text in ("Dassonville first version. " * 30, "Cassis second version. " * 30):
        retrieval.index_source(db, _fake_embed, course_id="eu", source="file", source_id="f1", name="notes.pdf",
                               kind="pdf", week="1", text=text, updated=0.0)
    all_text = " ".join(r["text"] for r in retrieval.search(rows, _fake_embed, course_id="eu", query="cassis", source_ids=["f1"]))
    assert "Cassis" in all_text and "first version" not in all_text        # replaced, not appended
    assert retrieval.search(rows, _fake_embed, course_id="eu", query="cassis", source_ids=["other"]) == []
    retrieval.forget_source(db, "file", "f1")
    assert retrieval.search(rows, _fake_embed, course_id="eu", query="cassis", source_ids=["f1"]) == []


# ---------------------------------------------------------------- the app's endpoints (retrieval switched on)

@pytest.fixture
def retrieval_on(client, monkeypatch):
    """Turn retrieval on with a stand-in embedder, so no model is downloaded in tests."""
    import run
    monkeypatch.setattr(run, "RETRIEVAL", True)
    monkeypatch.setattr(run.embed, "ready", lambda: True)
    monkeypatch.setattr(run.embed, "embed", _fake_embed)
    return client


def test_uploading_a_file_indexes_it_and_deleting_forgets_it(retrieval_on, pg):
    body = ("Dassonville dassonville dassonville. " * 40).encode()
    r = retrieval_on.post("/api/courses/eu/files", files={"file": ("W1 WG complete notes (annotated).txt", body, "text/plain")}, data={"week": "1"})
    fid = r.json()["id"]
    assert pg.execute("SELECT COUNT(*) FROM chunks WHERE source_id=%s", (fid,)).fetchone()[0] > 0
    retrieval_on.delete(f"/api/files/{fid}")
    assert pg.execute("SELECT COUNT(*) FROM chunks WHERE source_id=%s", (fid,)).fetchone()[0] == 0


def test_reindex_endpoint_counts_sources_and_is_repeatable(retrieval_on, pg):
    retrieval_on.post("/api/courses/eu/files", files={"file": ("W2 Lecture A transcript.txt", ("Cassis cassis. " * 40).encode(), "text/plain")}, data={"week": "2"})
    first = retrieval_on.post("/api/courses/eu/reindex").json()
    second = retrieval_on.post("/api/courses/eu/reindex").json()
    assert first["sources"] >= 1 and first["passages"] == second["passages"]     # replaced, never doubled


def test_search_puts_exact_matches_before_meaning_matches(retrieval_on):
    retrieval_on.post("/api/courses/eu/files", files={"file": ("W1 WG complete notes (annotated).txt", ("Dassonville formula. " * 40).encode(), "text/plain")}, data={"week": "1"})
    retrieval_on.post("/api/courses/eu/files", files={"file": ("W2 Lecture A transcript.txt", ("Packaging packaging rules. " * 40).encode(), "text/plain")}, data={"week": "2"})
    out = retrieval_on.get("/api/courses/eu/search", params={"q": "packaging"}).json()
    assert out, "search returned nothing"
    assert out[0].get("match") != "meaning"                                        # the word itself comes first
    assert any(o.get("match") == "meaning" for o in out) or len(out) == 1
