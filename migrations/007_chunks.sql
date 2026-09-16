-- Phase 10: passages of the user's own course materials, with embeddings, for course-first retrieval.
-- into public, and the column type is qualified, so migrating inside a scratch search_path still works
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS chunks(
    id         TEXT PRIMARY KEY,
    course_id  TEXT NOT NULL,
    source     TEXT NOT NULL,              -- 'file' | 'note'
    source_id  TEXT NOT NULL,              -- files.id or notes.id
    name       TEXT DEFAULT '',            -- file or note title, for the Reading strip
    kind       TEXT DEFAULT '',            -- pdf | text | note … (authority weighting)
    week       TEXT DEFAULT '',
    heading    TEXT DEFAULT '',            -- nearest heading, so a passage can be placed
    ord        INTEGER NOT NULL,           -- position within the source
    start_char INTEGER NOT NULL,
    text       TEXT NOT NULL,
    embedding  public.vector(384),
    updated    DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_chunks_course ON chunks(course_id, source, source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_vector ON chunks USING ivfflat (embedding public.vector_cosine_ops) WITH (lists = 100);
