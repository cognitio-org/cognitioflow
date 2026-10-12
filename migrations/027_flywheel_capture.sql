-- Phase 19: the flywheel. Phase 18 (026) captured card generation ONLY on the self-hosted path; this
-- captures EVERY generation (cloud AND local, Matej decision b) in card_gen_samples, and — far more
-- valuable — the CORRECTION signal: the pair (the AI's card -> Matej's edited card), which is what
-- actually teaches his taste. The last training experiment failed because the data lacked this signal.
-- Everything here is de-identified with the same pseudonymisation the privacy gateway uses (emails,
-- IBANs, student numbers, phone numbers -> placeholders) BEFORE anything is written. No name, account
-- or identity is kept. Additive: new table + new nullable columns; nothing existing changes shape.

-- THE GOLD: one row per edit of an AI-generated card (cards.gen_sample_id set), holding the before/after
-- pair. front_before/back_before is the card text as it stood just before this edit — on the FIRST edit
-- of a freshly generated card that is exactly the AI's original card; front_after/back_after is what
-- Matej saved. Joined to the generation interaction through gen_sample_id and to the card through
-- card_id. No foreign key, matching the additive style of cards.gen_sample_id.
CREATE TABLE IF NOT EXISTS card_edits(
    id            TEXT PRIMARY KEY,
    at            DOUBLE PRECISION NOT NULL,
    card_id       TEXT NOT NULL DEFAULT '',
    gen_sample_id TEXT NOT NULL DEFAULT '',
    course_id     TEXT NOT NULL DEFAULT '',
    front_before  TEXT NOT NULL DEFAULT '',
    back_before   TEXT NOT NULL DEFAULT '',
    front_after   TEXT NOT NULL DEFAULT '',
    back_after    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS card_edits_sample ON card_edits(gen_sample_id);
CREATE INDEX IF NOT EXISTS card_edits_at ON card_edits(at);

-- A lighter quality signal joined to the same interaction: each FSRS review rating of an AI-generated
-- card carries the gen_sample_id of the card it rated, so "this generated card was rated easy/again"
-- can be read back against the source that produced it. Additive + nullable: every other INSERT into
-- reviews leaves it NULL (it is set only when the reviewed card has a gen_sample_id).
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS gen_sample_id TEXT;
