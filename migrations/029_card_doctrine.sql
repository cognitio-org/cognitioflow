-- Tag each card with the examined blueprint topic (doctrine) it drills, so exam-readiness counts the
-- right cards per doctrine instead of guessing by substring. Empty '' means untagged — readiness then
-- falls back to the old text match for that card, so this is additive and safe before any tagging runs.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS doctrine TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_cards_doctrine ON cards(course_id, doctrine);
