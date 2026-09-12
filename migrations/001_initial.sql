-- Phase 1: initial Postgres schema (faithfully reproduced from SQLite + users table + user_id on courses)
-- Applied by: python -m migrate

CREATE TABLE IF NOT EXISTS users(
    id      TEXT PRIMARY KEY,
    email   TEXT UNIQUE NOT NULL,
    name    TEXT DEFAULT '',
    created DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS courses(
    id           TEXT PRIMARY KEY,
    name         TEXT,
    accent       TEXT,
    tutor_prompt TEXT DEFAULT '',
    created      DOUBLE PRECISION,
    user_id      TEXT REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS files(
    id        TEXT PRIMARY KEY,
    course_id TEXT,
    name      TEXT,
    kind      TEXT,
    path      TEXT,
    text      TEXT,
    chars     INTEGER,
    selected  INTEGER DEFAULT 1,
    status    TEXT,
    week      TEXT DEFAULT '',
    created   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS messages(
    id        TEXT PRIMARY KEY,
    course_id TEXT,
    role      TEXT,
    content   TEXT,
    created   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS notes(
    id        TEXT PRIMARY KEY,
    course_id TEXT,
    title     TEXT,
    body      TEXT,
    updated   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS cards(
    id        TEXT PRIMARY KEY,
    course_id TEXT,
    front     TEXT,
    back      TEXT,
    source    TEXT DEFAULT '',
    ease      DOUBLE PRECISION DEFAULT 2.5,
    interval  INTEGER DEFAULT 0,
    reps      INTEGER DEFAULT 0,
    due       TEXT,
    created   DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS reviews(
    id      TEXT PRIMARY KEY,
    card_id TEXT,
    rating  INTEGER,
    created DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS note_versions(
    id      TEXT PRIMARY KEY,
    note_id TEXT,
    title   TEXT,
    body    TEXT,
    created DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS recordings(
    id      TEXT PRIMARY KEY,
    note_id TEXT,
    path    TEXT,
    started DOUBLE PRECISION,
    seconds DOUBLE PRECISION DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions(
    id        TEXT PRIMARY KEY,
    course_id TEXT,
    day       TEXT,
    topic     TEXT,
    minutes   INTEGER,
    done      INTEGER DEFAULT 0
);

-- Indexes on every foreign-key column
CREATE INDEX IF NOT EXISTS idx_files_course_id         ON files(course_id);
CREATE INDEX IF NOT EXISTS idx_messages_course_id      ON messages(course_id);
CREATE INDEX IF NOT EXISTS idx_notes_course_id         ON notes(course_id);
CREATE INDEX IF NOT EXISTS idx_cards_course_id         ON cards(course_id);
CREATE INDEX IF NOT EXISTS idx_cards_due               ON cards(due);
CREATE INDEX IF NOT EXISTS idx_reviews_card_id         ON reviews(card_id);
CREATE INDEX IF NOT EXISTS idx_note_versions_note_id   ON note_versions(note_id);
CREATE INDEX IF NOT EXISTS idx_recordings_note_id      ON recordings(note_id);
CREATE INDEX IF NOT EXISTS idx_sessions_course_id      ON sessions(course_id);
