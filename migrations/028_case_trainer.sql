-- Phase 20: the exam-hypothetical case trainer. A "case" here is a realistic fact-pattern
-- hypothetical plus N multiple-choice questions that test the legal ISSUES in it (issue-spotting),
-- so Matej revises exam-style while doing MCQs. Each MCQ reuses the Phase-11 Question shape
-- {question, options[4], correct_index, explanation}; the fact pattern is the new wrapper.
--
-- Types and style match 001_initial.sql and 015_essay_practice.sql: ids are TEXT; created/seen are
-- epoch DOUBLE PRECISION set from Python, not a DB-side TIMESTAMP default; the option list is JSONB.
--
-- The tables are named case_hypos / case_hypo_mcqs, not `cases`, on purpose: the course domain already
-- uses "case" for case LAW (GET /api/courses/{cid}/cases is the case-law index built from the notes),
-- and these are exam hypotheticals, a different thing. The feature's routes are still /api/.../case/*.
--
-- Why not `essay_questions` or `cards`: a case is neither a single essay prompt nor a flashcard. It is
-- one fact pattern that OWNS several MCQs. The recurrence of a MISSED MCQ is handled by the app's one
-- review path (a card written on the miss, rated 'Again'), never by a second scheduler here — the same
-- reasoning oral.py's header and 015 set out.
CREATE TABLE IF NOT EXISTS case_hypos(
    id        TEXT PRIMARY KEY,
    course_id TEXT REFERENCES courses(id) ON DELETE CASCADE,
    week      TEXT DEFAULT '',
    length    TEXT DEFAULT 'short',   -- short | full — both selectable (settled 2026-10-12)
    facts     TEXT NOT NULL,          -- the fact-pattern hypothetical
    source    TEXT DEFAULT '',
    thin      INTEGER DEFAULT 0,      -- 1 when the writer flagged the ticked source as thin
    seen      DOUBLE PRECISION,       -- when this case was last served, so /next rotates through the bank
    created   DOUBLE PRECISION
);

-- One row per MCQ, in the Phase-11 Question shape {question, options[4], correct_index, explanation}.
-- `options` is a JSONB array of exactly four strings; `correct_index` is 0-3 into it; `explanation`
-- teaches (why right, why each wrong) and cites the material. `ord` keeps the MCQs in writing order.
CREATE TABLE IF NOT EXISTS case_hypo_mcqs(
    id            TEXT PRIMARY KEY,
    case_id       TEXT REFERENCES case_hypos(id) ON DELETE CASCADE,
    course_id     TEXT REFERENCES courses(id) ON DELETE CASCADE,
    ord           INTEGER DEFAULT 0,
    question      TEXT NOT NULL,
    options       JSONB NOT NULL,
    correct_index INTEGER DEFAULT 0,
    explanation   TEXT DEFAULT '',
    concept       TEXT DEFAULT '',
    created       DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_case_hypos_course ON case_hypos(course_id, week);
CREATE INDEX IF NOT EXISTS idx_case_hypo_mcqs_case ON case_hypo_mcqs(case_id, ord);
