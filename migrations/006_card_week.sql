-- Cards carry the week of the material they were made from, so Recall can filter flashcards and quizzes by week.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS week TEXT DEFAULT '';
-- Backfill cards generated from a single file (source = that file's name).
UPDATE cards c SET week = COALESCE((SELECT MIN(f.week) FROM files f WHERE f.course_id = c.course_id AND f.name = c.source AND f.week <> ''), '') WHERE COALESCE(c.week, '') = ''
