-- Read-only API keys (approved by Matej 2026-10-02, for Jarvis): a key reads Today, the due-card counts and weak
-- topics, and nothing else (auth.py READ_ROUTES). Only its SHA-256 is stored; the key itself is shown once, when
-- it is made. Revoking sets `revoked`; a revoked key is refused like an unknown one.
CREATE TABLE IF NOT EXISTS api_tokens(
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name      TEXT NOT NULL DEFAULT '',
    hash      TEXT NOT NULL UNIQUE,
    scope     TEXT NOT NULL DEFAULT 'read',
    created   DOUBLE PRECISION NOT NULL,
    last_used DOUBLE PRECISION,
    revoked   DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens(user_id);
