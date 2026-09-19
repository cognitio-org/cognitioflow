-- FSRS fits its parameters from a review log, not from the card's current state. The columns are the
-- snapshot at review time, so a scheduler change can be re-simulated over real history.
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS elapsed_days   INTEGER;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS scheduled_days INTEGER;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS state          INTEGER;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stability      DOUBLE PRECISION;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS difficulty     DOUBLE PRECISION;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS answer_ms      INTEGER;
CREATE INDEX IF NOT EXISTS idx_reviews_created ON reviews(created);
