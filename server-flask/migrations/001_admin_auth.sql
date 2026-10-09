CREATE TABLE IF NOT EXISTS administrators (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS administrator_sessions (
    token_hash CHAR(64) PRIMARY KEY,
    administrator_id BIGINT REFERENCES administrators(id) ON DELETE CASCADE,
    data JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS administrator_sessions_expiry_idx
    ON administrator_sessions (expires_at);

CREATE TABLE IF NOT EXISTS administrator_login_attempts (
    key_hash CHAR(64) PRIMARY KEY,
    attempts INTEGER NOT NULL,
    window_start TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
