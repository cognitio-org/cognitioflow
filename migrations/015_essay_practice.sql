-- Phase 17: essay practice — writing the answer, not just recalling the rule.
-- Types and style match migrations/001_initial.sql (ids are TEXT; created/updated are epoch
-- DOUBLE PRECISION set from Python, not a DB-side TIMESTAMP default).
--
-- Why not `cards`: a written answer is not a flashcard. It is long, it is marked as a comment per
-- move of the exam method rather than rated 0-3, and it must never enter the review queue — that
-- queue is the one place recurrence is decided and a second scheduler competing with it would
-- quietly undo it (the same reasoning oral.py's header sets out).
CREATE TABLE IF NOT EXISTS essay_questions(
    id        TEXT PRIMARY KEY,
    course_id TEXT REFERENCES courses(id) ON DELETE CASCADE,
    week      TEXT DEFAULT '',
    question  TEXT NOT NULL,
    model     TEXT DEFAULT '',
    source    TEXT DEFAULT '',
    created   DOUBLE PRECISION
);

-- One row per banked question (question_id is UNIQUE, so re-grading updates this row and never
-- writes a second bank entry). `answer` is written as it is typed, so a reload mid-write loses
-- nothing; `submitted` is what unlocks the model answer, and it is set before the marker is called
-- so a grader outage cannot lock away work already done.
CREATE TABLE IF NOT EXISTS essay_attempts(
    id          TEXT PRIMARY KEY,
    question_id TEXT UNIQUE REFERENCES essay_questions(id) ON DELETE CASCADE,
    course_id   TEXT REFERENCES courses(id) ON DELETE CASCADE,
    answer      TEXT DEFAULT '',
    grade       JSONB,
    submitted   DOUBLE PRECISION,
    created     DOUBLE PRECISION,
    updated     DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_essay_questions_course ON essay_questions(course_id, week);
CREATE INDEX IF NOT EXISTS idx_essay_attempts_course ON essay_attempts(course_id);
