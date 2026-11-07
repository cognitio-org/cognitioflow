-- Phase: multi-user — shared course CONTENT, PRIVATE per-user PROGRESS.
--
-- Course content (files, cards, notes, concepts, blueprint, essay_questions, authorities, case_hypos, …) stays
-- scoped by course; the course OWNER (courses.user_id) curates it and it is read-shared to allowed users. This
-- migration gives PROGRESS a user_id, lifts per-user card scheduling off the shared `cards` row into `card_state`,
-- and backfills every existing row to the single current user (matej@mgms.eu). It changes NO content tables.
--
-- SAFE TO RE-RUN: every step is IF [NOT] EXISTS or guarded by WHERE/ON CONFLICT. Depends on no higher-numbered
-- migration. The app still reads cards.* SR columns until the scheduler is switched to card_state in a follow-up
-- PR, so this migration ALONE changes no behaviour. On a fresh DB with no matej user row, every backfill is a no-op.

-- 1) PER-USER CARD SCHEDULING — the shared card keeps its text; each user's SR state lives in card_state.
CREATE TABLE IF NOT EXISTS card_state(
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id     TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    ease        DOUBLE PRECISION DEFAULT 2.5,
    interval    INTEGER DEFAULT 0,
    reps        INTEGER DEFAULT 0,
    due         TEXT,
    stability   DOUBLE PRECISION,
    difficulty  DOUBLE PRECISION,
    state       INTEGER,
    step        INTEGER,
    last_review DOUBLE PRECISION,
    created     DOUBLE PRECISION,
    PRIMARY KEY (user_id, card_id)
);
CREATE INDEX IF NOT EXISTS idx_card_state_user_due ON card_state(user_id, due);

-- backfill: the current user inherits each existing card's SR state so their schedule is preserved.
INSERT INTO card_state(user_id, card_id, ease, interval, reps, due, stability, difficulty, state, step, last_review, created)
SELECT u.id, c.id, c.ease, c.interval, c.reps, c.due, c.stability, c.difficulty, c.state, c.step, c.last_review, c.created
FROM cards c CROSS JOIN (SELECT id FROM users WHERE email = 'matej@mgms.eu' LIMIT 1) u
ON CONFLICT (user_id, card_id) DO NOTHING;

-- 2) PER-USER PROGRESS — add user_id, backfill to the current user, index it.
ALTER TABLE reviews         ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id);
ALTER TABLE messages        ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id);
ALTER TABLE sessions        ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id);
ALTER TABLE essay_attempts  ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id);
ALTER TABLE essay_revisions ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id);

UPDATE reviews         SET user_id = (SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE messages        SET user_id = (SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE sessions        SET user_id = (SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE essay_attempts  SET user_id = (SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE essay_revisions SET user_id = (SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_reviews_user         ON reviews(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_user        ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user        ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_essay_attempts_user  ON essay_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_essay_revisions_user ON essay_revisions(user_id);

-- essay_attempts was UNIQUE(question_id) — one attempt per question GLOBALLY. Make it one attempt per question PER USER.
ALTER TABLE essay_attempts DROP CONSTRAINT IF EXISTS essay_attempts_question_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_essay_attempts_user_question ON essay_attempts(user_id, question_id);

-- 3) OWNERSHIP of the seed content — the NULL-owner courses become the current user's (so they are not world-visible).
UPDATE courses SET user_id = (SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
