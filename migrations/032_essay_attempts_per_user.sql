-- Phase: multi-user progress scoping (PR #2) — private per-user chat / sessions / essays.
--
-- (1) BACKFILL the two-deploy gap. Between the 030 deploy and THIS one, the live app still inserted
--     messages/sessions/essay_attempts WITHOUT user_id (progress scoping ships in this PR), so those rows carry
--     user_id IS NULL. Stamp them to the single current user so his own recent chat/agenda/attempts stay visible
--     once the app scopes reads by user_id. No-op on a DB with no matej user row; idempotent.
UPDATE messages        SET user_id=(SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE sessions        SET user_id=(SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE essay_attempts  SET user_id=(SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;
UPDATE essay_revisions SET user_id=(SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;

-- (2) PER-USER essay attempts: ADD the UNIQUE(user_id, question_id) that _essay_save now conflicts on. We
--     deliberately KEEP the old essay_attempts_question_id_key for now — both constraints hold in a single-user DB
--     (one row per question satisfies each), so a rollback to the old _essay_save (ON CONFLICT (question_id))
--     still works against prod. A LATER migration drops the single-column unique once this code is proven live and
--     real multi-user needs two users to each hold an attempt on the same question. Idempotent.
CREATE UNIQUE INDEX IF NOT EXISTS idx_essay_attempts_user_question ON essay_attempts(user_id, question_id);
