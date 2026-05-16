CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(100) NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    sources         JSONB,
    rewritten_query TEXT,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  VARCHAR(100) NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    rating      VARCHAR(10) NOT NULL CHECK (rating IN ('up', 'down')),
    comment     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
