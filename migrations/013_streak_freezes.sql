-- Phase 15: the streak freeze ledger. The streak itself stays derived from reviews — there is no
-- counter column here and must never be one. This table only records which missed days were
-- forgiven, so the number on the home screen can say when it was kept alive and by what.
-- Types and style match migrations/001_initial.sql (TEXT ids, ISO-date TEXT days like sessions.day,
-- created is an epoch DOUBLE PRECISION set from Python).
CREATE TABLE IF NOT EXISTS streak_freezes(
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    day       TEXT NOT NULL,
    created   DOUBLE PRECISION,
    PRIMARY KEY (course_id, day)
);

CREATE INDEX IF NOT EXISTS idx_streak_freezes_course_id ON streak_freezes(course_id);
