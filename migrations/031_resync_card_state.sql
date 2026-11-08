-- Phase: multi-user scheduler switch. The app now reads/writes per-user SR from card_state (not the shared cards.*).
--
-- Why a second backfill: migration 030 seeded card_state from cards.* at ITS apply time. Between the 030 deploy and
-- THIS PR's deploy, the old code kept writing cards.* on every review, so 030's card_state copy is stale by exactly
-- those reviews. At 031 apply time cards.* is still the authoritative per-user schedule (the new code isn't live yet),
-- so we re-copy it into card_state, overwriting unconditionally. After this PR deploys, card_state becomes the source
-- of truth and cards.* goes vestigial (dropped in a later cleanup).
--
-- SAFE / IDEMPOTENT: re-running overwrites with the same values. No-op on a DB with no matej user row. Touches only
-- the current user's private card_state rows — no content tables, no other user. Rolling back to pre-030 after this
-- deploys would strand reviews recorded only in card_state; acceptable for a single user, noted in the PR.

INSERT INTO card_state(user_id, card_id, ease, interval, reps, due, stability, difficulty, state, step, last_review, created)
SELECT u.id, c.id, c.ease, c.interval, c.reps, c.due, c.stability, c.difficulty, c.state, c.step, c.last_review, c.created
FROM cards c CROSS JOIN (SELECT id FROM users WHERE email = 'matej@mgms.eu' LIMIT 1) u
ON CONFLICT (user_id, card_id) DO UPDATE SET
    ease        = EXCLUDED.ease,
    interval    = EXCLUDED.interval,
    reps        = EXCLUDED.reps,
    due         = EXCLUDED.due,
    stability   = EXCLUDED.stability,
    difficulty  = EXCLUDED.difficulty,
    state       = EXCLUDED.state,
    step        = EXCLUDED.step,
    last_review = EXCLUDED.last_review;
