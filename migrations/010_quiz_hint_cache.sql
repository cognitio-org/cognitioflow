-- Phase 11g: cache backend results for quiz distractors and hints so a repeat call skips CHEAP_MODEL.
-- Types and style match migrations/001_initial.sql (courses.id / cards.id are TEXT; created is an
-- epoch DOUBLE PRECISION set from Python, not a DB-side TIMESTAMP default).
CREATE TABLE IF NOT EXISTS card_distractors(
    card_id   TEXT PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    back_hash TEXT NOT NULL,
    wrong     JSONB NOT NULL,
    model     TEXT,
    created   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS hint_cache(
    key       TEXT PRIMARY KEY,
    course_id TEXT REFERENCES courses(id) ON DELETE CASCADE,
    hint      TEXT NOT NULL,
    model     TEXT,
    created   DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_hint_cache_course_id ON hint_cache(course_id);
