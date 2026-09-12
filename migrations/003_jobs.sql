-- Phase 3: durable transcription jobs. Job state lives here, never in process memory.
CREATE TABLE IF NOT EXISTS jobs(
    id       TEXT PRIMARY KEY,
    kind     TEXT NOT NULL,
    ref_id   TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'queued',
    stage    TEXT DEFAULT '',
    executor TEXT DEFAULT 'hosted',
    payload  JSONB DEFAULT '{}',
    result   JSONB DEFAULT '{}',
    error    TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    created  DOUBLE PRECISION,
    updated  DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_jobs_ref_kind ON jobs(ref_id, kind);
-- At most one live (non-failed) job per recording, even if two clicks race.
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_live ON jobs(ref_id, kind) WHERE status <> 'failed'
