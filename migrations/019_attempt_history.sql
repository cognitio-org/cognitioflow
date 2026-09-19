-- Feedback only pays off through a revision, so every draft is kept rather than overwritten, and
-- marks are held per criterion. No aggregate score column on purpose: a number shown next to
-- comments suppresses the effect of the comments, so the app must not be able to display one.
ALTER TABLE essay_attempts ADD COLUMN IF NOT EXISTS criteria  JSONB;                 -- [{"step":"Applicability","met":true,"comment":"..."}]
ALTER TABLE essay_attempts ADD COLUMN IF NOT EXISTS marked_by TEXT DEFAULT '';       -- the model that marked it, never the one that coached
ALTER TABLE essay_attempts ADD COLUMN IF NOT EXISTS seconds   DOUBLE PRECISION;      -- time spent writing, for timed drills
ALTER TABLE essay_attempts ADD COLUMN IF NOT EXISTS revisions INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS essay_revisions(
    id          TEXT PRIMARY KEY,
    attempt_id  TEXT REFERENCES essay_attempts(id) ON DELETE CASCADE,
    question_id TEXT REFERENCES essay_questions(id) ON DELETE CASCADE,
    course_id   TEXT REFERENCES courses(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL DEFAULT 1,          -- 1 is the first draft
    answer      TEXT NOT NULL,
    criteria    JSONB,
    marked_by   TEXT DEFAULT '',
    seconds     DOUBLE PRECISION,
    created     DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_essay_revisions_attempt ON essay_revisions(attempt_id, ord);
CREATE INDEX IF NOT EXISTS idx_essay_revisions_course ON essay_revisions(course_id, created);
