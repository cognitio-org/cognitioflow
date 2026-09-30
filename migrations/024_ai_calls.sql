-- One row per AI call: which feature asked, which model answered, the tokens and what it cost.
-- cost_usd is NULL when the bill is not known (openrouter sent no figure, or the model has no price):
-- a spend line built on guesses is worse than one that says what it does not know.
-- No prompt, reply, note or file text is kept here - only counts and names.
CREATE TABLE IF NOT EXISTS ai_calls(
    id                  TEXT PRIMARY KEY,
    at                  DOUBLE PRECISION NOT NULL,
    user_id             TEXT,
    feature             TEXT NOT NULL DEFAULT '',
    provider            TEXT NOT NULL DEFAULT '',
    model               TEXT NOT NULL DEFAULT '',
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd            DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ai_calls_at ON ai_calls(at);
