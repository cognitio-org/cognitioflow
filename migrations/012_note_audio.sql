-- Phase 14: audio the app made from a note (the student's own recordings stay in `recordings`).
-- One row per note. `key` is a storage.py key, never a filesystem path. `fingerprint` is what the
-- audio was made from, so an edited note stops matching it and the next request regenerates;
-- `voice` is the backend that spoke it, so changing the app's voice regenerates too.
CREATE TABLE IF NOT EXISTS note_audio(
    note_id     TEXT PRIMARY KEY,
    key         TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    voice       TEXT NOT NULL DEFAULT '',
    chars       INTEGER DEFAULT 0,
    bytes       INTEGER DEFAULT 0,
    created     DOUBLE PRECISION
);
