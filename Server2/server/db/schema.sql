-- Server 2 tables only. Idempotent boot migrations.

CREATE TABLE IF NOT EXISTS server_health (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_boot TIMESTAMPTZ NOT NULL,
    CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS facts (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    source TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ,
    superseded_by UUID REFERENCES facts (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS facts_user_key_active_idx
    ON facts (user_id, key)
    WHERE active = true;

CREATE INDEX IF NOT EXISTS facts_user_key_idx ON facts (user_id, key, active);
CREATE INDEX IF NOT EXISTS facts_user_created_idx ON facts (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    client_meta JSONB NOT NULL DEFAULT '{}',
    compressed_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions (user_id);

CREATE TABLE IF NOT EXISTS turns (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS turns_session_created_idx ON turns (session_id, created_at DESC);
