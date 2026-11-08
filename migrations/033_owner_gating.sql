-- Phase: multi-user owner-gating (PR #3) — content is read-shared to every allowed user but EDITED only by its
-- owner (courses.user_id). Two schema moves back the app-level gating that lands in the same PR.
--
-- (1) BACKFILL legacy NULL course owners. courses.user_id has existed since 001 but was never backfilled: a course
--     created before Google sign-in (or seeded directly) can carry user_id IS NULL, and the app treats that as a
--     real case (COALESCE(user_id,'') appears in the slug index and add_course). The new _own_course() gate fails
--     CLOSED (owner != caller -> 403), so a NULL-owner course would become uneditable by anyone. Stamp any such
--     course to the single current user so ownership is always concrete. No-op on a DB with no matej row (fresh
--     test DBs create courses through the API with the owner already set); idempotent.
UPDATE courses SET user_id=(SELECT id FROM users WHERE email='matej@mgms.eu' LIMIT 1) WHERE user_id IS NULL;

-- (2) DROP the single-column essay unique. 015 created essay_attempts.question_id as `TEXT UNIQUE`, which Postgres
--     auto-named essay_attempts_question_id_key. 032 added the per-user UNIQUE(user_id, question_id) index while
--     deliberately KEEPING this one, so a rollback to the old _essay_save (ON CONFLICT (question_id)) still worked.
--     That code is now proven live (shipped in #180). While essay_attempts_question_id_key survives, only ONE row
--     per question can exist across ALL users, so a second user cannot hold their own attempt on a question a
--     classmate already answered. Dropping it moves per-user uniqueness entirely onto idx_essay_attempts_user_question.
--     Idempotent: a reapply finds the constraint already gone.
ALTER TABLE essay_attempts DROP CONSTRAINT IF EXISTS essay_attempts_question_id_key;
