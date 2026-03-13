BEGIN;

CREATE TABLE IF NOT EXISTS auth_claim_replay_guard (
  jti UUID PRIMARY KEY,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_claim_replay_guard_expires_at
  ON auth_claim_replay_guard (expires_at);

CREATE TABLE IF NOT EXISTS api_rate_limit_guard (
  principal_key TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  request_count INTEGER NOT NULL CHECK (request_count >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (principal_key, window_start)
);

CREATE INDEX IF NOT EXISTS idx_api_rate_limit_guard_window_start
  ON api_rate_limit_guard (window_start);

COMMIT;
