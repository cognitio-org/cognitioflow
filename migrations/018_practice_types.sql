-- Practice is decomposed, not one "write an essay" button: issue spotting, rule-plus-authority,
-- application and counter-argument are separate drills, and a Dutch answer follows a stappenplan
-- rather than IRAC. steps holds that plan as the marking criteria for this question.
ALTER TABLE essay_questions ADD COLUMN IF NOT EXISTS kind   TEXT DEFAULT 'problem';  -- problem | issue | rule | application | counter
ALTER TABLE essay_questions ADD COLUMN IF NOT EXISTS steps  JSONB;                   -- [{"step": "Applicability", "looks_for": "..."}]
ALTER TABLE essay_questions ADD COLUMN IF NOT EXISTS retired INTEGER DEFAULT 0;      -- a question that turned out to be wrong, kept for its attempts
CREATE INDEX IF NOT EXISTS idx_essay_questions_kind ON essay_questions(course_id, kind, week);
