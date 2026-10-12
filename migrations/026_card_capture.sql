-- Phase 18: de-identified capture of card-generation interactions, so a cards specialist can be
-- trained later from real work instead of invented data. Identity and personal content are stripped
-- BEFORE anything is written here (the same pseudonymisation the privacy gateway uses: emails, IBANs,
-- student numbers and phone numbers become placeholders). Only the system interaction is kept — the
-- source material and the cards it produced — never a name, an account or an identity. The feedback
-- signal (later card edits and FSRS ratings) is joined in through cards.gen_sample_id, not copied here.
CREATE TABLE IF NOT EXISTS card_gen_samples(
    id            TEXT PRIMARY KEY,
    at            DOUBLE PRECISION NOT NULL,
    course_id     TEXT NOT NULL DEFAULT '',
    provider      TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    source_kind   TEXT NOT NULL DEFAULT '',
    week          TEXT NOT NULL DEFAULT '',
    grounded      BOOLEAN NOT NULL DEFAULT FALSE,
    thin          BOOLEAN NOT NULL DEFAULT FALSE,
    requested     INTEGER NOT NULL DEFAULT 0,
    made          INTEGER NOT NULL DEFAULT 0,
    source_chars  INTEGER NOT NULL DEFAULT 0,
    source_text   TEXT NOT NULL DEFAULT '',
    cards_json    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS card_gen_samples_at ON card_gen_samples(at);

-- Tie each generated card back to its capture row, so the later feedback signal (edits, FSRS ratings)
-- can be joined to the interaction that produced it. Nullable and additive: every other INSERT into
-- cards leaves it NULL, and nothing reads it yet.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS gen_sample_id TEXT;
