-- Write-scoped API tokens (approved by Matej 2026-11-09, for the lecture pipeline). A cfw_ token may POST a
-- finished lecture note to exactly ONE bound course's /files and /cards/generate, and nothing else — enforced at
-- the AuthMiddleware edge (auth.py), independent of _require_owner. Read keys (cfr_) are entirely unaffected.
--   course_id  the single course this key may write to (NULL for a read key).
--   expires    hard expiry (epoch seconds); a key past it is refused like a revoked one. NULL for read keys.
-- Narrow + short-lived by construction, so a leaked write key is low-blast-radius. Idempotent.
ALTER TABLE api_tokens ADD COLUMN IF NOT EXISTS course_id TEXT REFERENCES courses(id) ON DELETE CASCADE;
ALTER TABLE api_tokens ADD COLUMN IF NOT EXISTS expires   DOUBLE PRECISION;
