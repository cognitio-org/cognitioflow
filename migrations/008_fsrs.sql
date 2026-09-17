-- Phase 10: FSRS scheduling. SM-2's ease/interval/reps stay, so SCHEDULER=sm2 keeps working and nothing is lost.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS stability   DOUBLE PRECISION;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS difficulty  DOUBLE PRECISION;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS state       INTEGER;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS step        INTEGER;
ALTER TABLE cards ADD COLUMN IF NOT EXISTS last_review DOUBLE PRECISION;
