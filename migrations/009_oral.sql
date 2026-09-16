-- Phase 11c: oral revision. A spoken question is a card with two extra things the tutor needs:
--   concept — the thing being tested, so a miss can pull every question on that idea forward
--   traps   — the wrong turns to listen for, so grading catches the near-miss answer
ALTER TABLE cards ADD COLUMN IF NOT EXISTS concept TEXT DEFAULT '';
ALTER TABLE cards ADD COLUMN IF NOT EXISTS traps   TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_cards_concept ON cards(course_id, concept);
