-- The Planner cannot be right and the scheduler has no target while a course does not know when it
-- starts or when its exam is. brief.period and brief.exam_date are free text for the tutor prompt,
-- these two are dates the app can compute with.
ALTER TABLE courses ADD COLUMN IF NOT EXISTS term_start TEXT DEFAULT '';   -- YYYY-MM-DD, Monday of teaching week 1
ALTER TABLE courses ADD COLUMN IF NOT EXISTS exam_date  TEXT DEFAULT '';   -- YYYY-MM-DD of the written paper
ALTER TABLE courses ADD COLUMN IF NOT EXISTS week_days  INTEGER DEFAULT 7; -- length of a teaching week, for courses that do not run Mon-Sun
