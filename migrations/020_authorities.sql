-- A citation is checkable only against a list of authorities that exist. ECLI (national and EU) and
-- CELEX are free, stable and machine-readable, so every case and instrument the course materials
-- name gets a row here. a tutor citation resolving to no row is reported, not printed.
CREATE TABLE IF NOT EXISTS authorities(
    id         TEXT PRIMARY KEY,
    course_id  TEXT REFERENCES courses(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL DEFAULT 'case',   -- case | article | instrument
    key        TEXT NOT NULL,                  -- ECLI:EU:C:1974:82, CELEX 32004L0038, "Art 34 TFEU"
    name       TEXT DEFAULT '',                -- Dassonville
    cite       TEXT DEFAULT '',                -- C-8/74, as the notes write it
    year       INTEGER,
    url        TEXT DEFAULT '',
    seen_in    TEXT DEFAULT '',                -- file or note id it was first read from
    verified   INTEGER DEFAULT 0,              -- 1 once resolved against EUR-Lex/CURIA/rechtspraak
    created    DOUBLE PRECISION
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_authorities_key ON authorities(course_id, key);
CREATE INDEX IF NOT EXISTS idx_authorities_name ON authorities(course_id, name);
