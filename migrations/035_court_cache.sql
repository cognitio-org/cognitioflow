-- Games: remove play-time external-AI dependency. Cache a built moot hearing so the "Cases" feature
-- serves it from Postgres at play-time instead of calling a cloud model on the student's request.
-- The hearing is a pure function of the case + the student's own notes, so the key is a hash of those
-- (run.py:_court_key). Mirrors migrations/010_quiz_hint_cache.sql exactly: TEXT ids, `created` an
-- epoch DOUBLE PRECISION set from Python, JSONB payload decoded straight back to a dict.
CREATE TABLE IF NOT EXISTS court_cache(
    key       TEXT PRIMARY KEY,
    course_id TEXT REFERENCES courses(id) ON DELETE CASCADE,
    hearing   JSONB NOT NULL,
    model     TEXT,
    created   DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_court_cache_course_id ON court_cache(course_id);
