-- Case Docket games written from his own files. A game is a draft until he approves it; only approved games
-- reach the 3D player's library. The hand-made games in play/games/ stay where they are.
CREATE TABLE IF NOT EXISTS docket_games(
    id          TEXT PRIMARY KEY,
    course_id   TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    week        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'writing',   -- writing | draft | approved | discarded | failed
    title       TEXT NOT NULL DEFAULT '',
    game        JSONB,                             -- the player's game JSON
    review      JSONB,                             -- {"issues": [...], "unverified": [...], "revised": bool}
    files       JSONB,                             -- ids of the files it was written from
    error       TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    created     DOUBLE PRECISION,
    updated     DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS docket_games_course ON docket_games(course_id, status);
