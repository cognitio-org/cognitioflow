-- A concept is the thing a question is about, held once and reused, instead of being re-derived from
-- raw text every time a card is written. It is what lets a doctrine met in week 2 be recognised again
-- in week 5, and what lets the same reasoning be recognised in another course.
CREATE TABLE IF NOT EXISTS concepts(
    id          TEXT PRIMARY KEY,
    course_id   TEXT REFERENCES courses(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,                  -- "Dassonville formula", "Numerus clausus"
    kind        TEXT NOT NULL DEFAULT 'rule',   -- rule | test | case | article | doctrine | exception
    week        TEXT DEFAULT '',
    statement   TEXT DEFAULT '',                -- the rule in one or two sentences, in the course's own words
    limbs       JSONB,                          -- ["a measure...", "capable of hindering...", "directly or indirectly"]
    traps       JSONB,                          -- ["treating Cassis as an alternative to Dassonville rather than the next step"]
    authority   TEXT DEFAULT '',                -- authorities.key: an ECLI, a CELEX id, "Art 34 TFEU"
    source_file TEXT DEFAULT '',                -- files.id it was read from
    source_note TEXT DEFAULT '',                -- notes.id it was read from
    chunk_id    TEXT DEFAULT '',                -- chunks.id: the passage the statement must be derivable from
    method_tag  TEXT DEFAULT '',                -- proportionality | direct effect | remedies | burden of proof ...
    created     DOUBLE PRECISION,
    updated     DOUBLE PRECISION
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_concepts_name ON concepts(course_id, lower(name));
CREATE INDEX IF NOT EXISTS idx_concepts_week ON concepts(course_id, week);
CREATE INDEX IF NOT EXISTS idx_concepts_method ON concepts(method_tag);

-- Siblings. Interleaving pays when the categories are confusable, which is a property of the pair,
-- not of the deck: Dassonville/Cassis/Keck, direct effect/indirect effect/state liability. A link
-- across courses is the same reasoning in different clothes, which is the comparison worth drilling.
CREATE TABLE IF NOT EXISTS concept_links(
    id        TEXT PRIMARY KEY,
    a_id      TEXT REFERENCES concepts(id) ON DELETE CASCADE,
    b_id      TEXT REFERENCES concepts(id) ON DELETE CASCADE,
    relation  TEXT NOT NULL DEFAULT 'confusable',   -- confusable | follows | narrows | same-method
    note      TEXT DEFAULT '',                      -- what the difference actually is
    created   DOUBLE PRECISION
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_links_pair ON concept_links(a_id, b_id, relation);

-- What a question is about, so a week can be covered rather than merely quizzed.
ALTER TABLE cards ADD COLUMN IF NOT EXISTS concept_id TEXT;
ALTER TABLE essay_questions ADD COLUMN IF NOT EXISTS concept_id TEXT;
CREATE INDEX IF NOT EXISTS idx_cards_concept ON cards(concept_id);
CREATE INDEX IF NOT EXISTS idx_essay_questions_concept ON essay_questions(concept_id);
