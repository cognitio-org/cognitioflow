-- Multi-user readiness: invites, per-user privacy settings, per-user cost lookups.
--
-- PURELY ADDITIVE and behaviour-neutral on its own: new tables, one nullable column, indexes. Nothing in run.py or
-- auth.py reads these until docs/multi-user/protected-changes.patch is applied (Matej's named yes). Migrations run at
-- app start, so this file reaches production when the PR deploys - which is why it changes no existing behaviour.
-- SAFE TO RE-RUN: every statement is IF [NOT] EXISTS or guarded.

-- 1) INVITES - the owner records an address; auth admits it (once the auth.py patch lands) in addition to
--    ALLOWED_EMAILS. Nothing is ever sent from here: the owner shares the link himself.
CREATE TABLE IF NOT EXISTS invites(
    email      TEXT PRIMARY KEY,                                   -- lower-cased by the app
    invited_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    note       TEXT NOT NULL DEFAULT '',
    created    DOUBLE PRECISION NOT NULL,
    revoked    DOUBLE PRECISION,                                   -- set = no longer admitted
    accepted   DOUBLE PRECISION                                    -- first sign-in after the invite
);

-- 2) PER-USER PRIVACY SETTINGS - consent for the de-identified training capture (Art. 6(1)(a) / Art. 25 default off for
--    everyone but the owner) and when the privacy notice was acknowledged.
CREATE TABLE IF NOT EXISTS user_prefs(
    user_id         TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    capture_consent INTEGER,                                       -- NULL never asked, 0 no, 1 yes
    privacy_ack     DOUBLE PRECISION,
    updated         DOUBLE PRECISION
);

-- 3) PER-USER COST CAPS read ai_calls by (user_id, at); ai_calls.user_id already exists (024) and _log_call fills it.
CREATE INDEX IF NOT EXISTS ai_calls_user_at ON ai_calls(user_id, at);

-- 4) STREAK-FREEZE LEDGER attribution. The streak itself is derived from the caller's own reviews (no cross-user
--    effect); only this write-only ledger is keyed by course. Add the column now (nullable, unused); the key change
--    and the write that fills it ship together in the protected patch (036 there), so nothing half-lands.
ALTER TABLE streak_freezes ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
