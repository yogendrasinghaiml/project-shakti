-- SHAKTI V3 - Phase 2 Schema Foundation
-- Target: PostgreSQL 16 + PostGIS
-- Security goals:
-- 1) Strict RBAC with clearance levels
-- 2) Auditable writes on every table
-- 3) Geospatial-native intelligence model
-- 4) High-integrity sensor telemetry pipeline

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'clearance_level') THEN
    CREATE TYPE clearance_level AS ENUM (
      'UNCLASSIFIED',
      'CONFIDENTIAL',
      'SECRET',
      'TOP_SECRET'
    );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'unit_type') THEN
    CREATE TYPE unit_type AS ENUM (
      'FRIENDLY',
      'HOSTILE',
      'UNKNOWN'
    );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'source_type') THEN
    CREATE TYPE source_type AS ENUM (
      'REST_HOOK',
      'MQTT_SENSOR',
      'MANUAL',
      'FUSION'
    );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_status') THEN
    CREATE TYPE review_status AS ENUM (
      'PENDING_MANUAL_REVIEW',
      'APPROVED',
      'REJECTED'
    );
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Shared utilities
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION clearance_to_rank(v clearance_level)
RETURNS integer
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE v
    WHEN 'UNCLASSIFIED' THEN 10
    WHEN 'CONFIDENTIAL' THEN 20
    WHEN 'SECRET' THEN 30
    WHEN 'TOP_SECRET' THEN 40
  END;
$$;

CREATE OR REPLACE FUNCTION session_clearance()
RETURNS clearance_level
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v text;
BEGIN
  v := current_setting('app.user_clearance', true);
  IF v IS NULL OR v = '' THEN
    RETURN 'UNCLASSIFIED'::clearance_level;
  END IF;
  RETURN v::clearance_level;
EXCEPTION
  WHEN OTHERS THEN
    RETURN 'UNCLASSIFIED'::clearance_level;
END;
$$;

CREATE OR REPLACE FUNCTION block_policy_decisions_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'policy_decisions is append-only: DELETE is not allowed';
END;
$$;

-- ---------------------------------------------------------------------------
-- Identity and RBAC
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  email TEXT UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  clearance_level clearance_level NOT NULL DEFAULT 'UNCLASSIFIED',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID
);

INSERT INTO users (
  user_id,
  username,
  display_name,
  is_active,
  clearance_level,
  last_modified_by
)
VALUES (
  '00000000-0000-0000-0000-000000000000'::uuid,
  'system-service',
  'System Service Principal',
  TRUE,
  'TOP_SECRET'::clearance_level,
  '00000000-0000-0000-0000-000000000000'::uuid
)
ON CONFLICT (user_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS roles (
  role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  role_name TEXT NOT NULL UNIQUE,
  description TEXT,
  min_clearance_required clearance_level NOT NULL DEFAULT 'UNCLASSIFIED',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS permissions (
  permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  permission_key TEXT NOT NULL UNIQUE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id),
  UNIQUE (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role_permission_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  role_id UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
  permission_id UUID NOT NULL REFERENCES permissions(permission_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id),
  UNIQUE (role_id, permission_id)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'users_last_modified_by_fk'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT users_last_modified_by_fk
      FOREIGN KEY (last_modified_by)
      REFERENCES users(user_id);
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Geospatial domain model
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sectors (
  sector_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sector_code TEXT NOT NULL UNIQUE,
  sector_name TEXT NOT NULL,
  boundary geometry(POLYGON, 4326) NOT NULL,
  default_classification clearance_level NOT NULL DEFAULT 'CONFIDENTIAL',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_sectors_boundary_gist
  ON sectors USING GIST (boundary);

CREATE TABLE IF NOT EXISTS targets (
  target_id TEXT PRIMARY KEY,
  target_label TEXT,
  unit_type unit_type NOT NULL DEFAULT 'UNKNOWN',
  canonical_classification clearance_level NOT NULL DEFAULT 'CONFIDENTIAL',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS intel_observations (
  observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  target_id TEXT NOT NULL REFERENCES targets(target_id),
  source_id TEXT NOT NULL,
  source_type source_type NOT NULL,
  sensor_id UUID,
  sector_id UUID REFERENCES sectors(sector_id),
  classification_marking clearance_level NOT NULL,
  confidence NUMERIC(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  observed_at TIMESTAMPTZ NOT NULL,
  location geometry(POINT, 4326) NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_intel_target_observed
  ON intel_observations (target_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_intel_source_observed
  ON intel_observations (source_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_intel_location_gist
  ON intel_observations USING GIST (location);
CREATE INDEX IF NOT EXISTS idx_intel_payload_gin
  ON intel_observations USING GIN (payload);

CREATE TABLE IF NOT EXISTS target_tracks (
  track_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  target_id TEXT NOT NULL REFERENCES targets(target_id),
  path geometry(LINESTRING, 4326) NOT NULL,
  first_seen TIMESTAMPTZ NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL,
  classification_marking clearance_level NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_target_tracks_path_gist
  ON target_tracks USING GIST (path);

CREATE TABLE IF NOT EXISTS coordinate_conflicts (
  conflict_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  target_id TEXT NOT NULL REFERENCES targets(target_id),
  left_observation_id UUID NOT NULL REFERENCES intel_observations(observation_id),
  right_observation_id UUID NOT NULL REFERENCES intel_observations(observation_id),
  distance_meters NUMERIC(12,3) NOT NULL CHECK (distance_meters >= 0),
  classification_marking clearance_level NOT NULL,
  status review_status NOT NULL DEFAULT 'PENDING_MANUAL_REVIEW',
  conflict_reason TEXT NOT NULL,
  resolved_by UUID REFERENCES users(user_id),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

ALTER TABLE coordinate_conflicts
  ADD COLUMN IF NOT EXISTS classification_marking clearance_level;
UPDATE coordinate_conflicts
SET classification_marking = 'CONFIDENTIAL'::clearance_level
WHERE classification_marking IS NULL;
ALTER TABLE coordinate_conflicts
  ALTER COLUMN classification_marking SET DEFAULT 'CONFIDENTIAL'::clearance_level;
ALTER TABLE coordinate_conflicts
  ALTER COLUMN classification_marking SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_conflicts_status
  ON coordinate_conflicts (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conflicts_classification
  ON coordinate_conflicts (classification_marking, status, created_at DESC);

-- ---------------------------------------------------------------------------
-- Sensor telemetry (specialized)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_registry (
  sensor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sensor_code TEXT NOT NULL UNIQUE,
  sensor_type TEXT NOT NULL,
  site_location geometry(POINT, 4326),
  max_classification clearance_level NOT NULL DEFAULT 'SECRET',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_sensor_registry_location_gist
  ON sensor_registry USING GIST (site_location);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'intel_observations_sensor_fk'
  ) THEN
    ALTER TABLE intel_observations
      ADD CONSTRAINT intel_observations_sensor_fk
      FOREIGN KEY (sensor_id)
      REFERENCES sensor_registry(sensor_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS sensor_logs (
  sensor_log_id UUID NOT NULL DEFAULT gen_random_uuid(),
  sensor_id UUID NOT NULL REFERENCES sensor_registry(sensor_id),
  observed_at TIMESTAMPTZ NOT NULL,
  classification_marking clearance_level NOT NULL,
  signal_type TEXT NOT NULL,
  signal_strength NUMERIC(8,3),
  raw_payload JSONB NOT NULL,
  parsed_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  ingest_channel source_type NOT NULL DEFAULT 'MQTT_SENSOR',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id),
  PRIMARY KEY (sensor_log_id, observed_at)
) PARTITION BY RANGE (observed_at);

CREATE TABLE IF NOT EXISTS sensor_logs_2026_03
  PARTITION OF sensor_logs
  FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');

CREATE TABLE IF NOT EXISTS sensor_logs_default
  PARTITION OF sensor_logs
  DEFAULT;

CREATE INDEX IF NOT EXISTS idx_sensor_logs_sensor_time
  ON sensor_logs (sensor_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_sensor_logs_payload_gin
  ON sensor_logs USING GIN (raw_payload);

-- ---------------------------------------------------------------------------
-- Fusion, policy, and auditing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fusion_reports (
  report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_ref TEXT NOT NULL UNIQUE,
  report_title TEXT NOT NULL,
  summary_markdown TEXT NOT NULL,
  classification_marking clearance_level NOT NULL,
  generated_by UUID REFERENCES users(user_id),
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS fusion_report_observations (
  link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID NOT NULL REFERENCES fusion_reports(report_id) ON DELETE CASCADE,
  observation_id UUID NOT NULL REFERENCES intel_observations(observation_id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id),
  UNIQUE (report_id, observation_id)
);

CREATE TABLE IF NOT EXISTS policy_decisions (
  decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id UUID REFERENCES fusion_reports(report_id),
  escalation_level TEXT NOT NULL,
  rule_name TEXT NOT NULL,
  rationale TEXT NOT NULL,
  data_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  operator_reviewed BOOLEAN NOT NULL DEFAULT FALSE,
  review_notes TEXT,
  classification_marking clearance_level NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
  audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id UUID REFERENCES users(user_id),
  actor_role TEXT,
  action_type TEXT NOT NULL,
  entity_name TEXT NOT NULL,
  entity_id TEXT,
  request_id TEXT,
  source_ip INET,
  classification_marking clearance_level,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_modified_by UUID REFERENCES users(user_id)
);

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

-- ---------------------------------------------------------------------------
-- updated_at triggers (all auditable tables)
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_roles_updated_at ON roles;
CREATE TRIGGER trg_roles_updated_at
BEFORE UPDATE ON roles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_permissions_updated_at ON permissions;
CREATE TRIGGER trg_permissions_updated_at
BEFORE UPDATE ON permissions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_roles_updated_at ON user_roles;
CREATE TRIGGER trg_user_roles_updated_at
BEFORE UPDATE ON user_roles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_role_permissions_updated_at ON role_permissions;
CREATE TRIGGER trg_role_permissions_updated_at
BEFORE UPDATE ON role_permissions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_sectors_updated_at ON sectors;
CREATE TRIGGER trg_sectors_updated_at
BEFORE UPDATE ON sectors
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_targets_updated_at ON targets;
CREATE TRIGGER trg_targets_updated_at
BEFORE UPDATE ON targets
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_intel_observations_updated_at ON intel_observations;
CREATE TRIGGER trg_intel_observations_updated_at
BEFORE UPDATE ON intel_observations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_target_tracks_updated_at ON target_tracks;
CREATE TRIGGER trg_target_tracks_updated_at
BEFORE UPDATE ON target_tracks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_coordinate_conflicts_updated_at ON coordinate_conflicts;
CREATE TRIGGER trg_coordinate_conflicts_updated_at
BEFORE UPDATE ON coordinate_conflicts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_sensor_registry_updated_at ON sensor_registry;
CREATE TRIGGER trg_sensor_registry_updated_at
BEFORE UPDATE ON sensor_registry
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_sensor_logs_updated_at ON sensor_logs;
CREATE TRIGGER trg_sensor_logs_updated_at
BEFORE UPDATE ON sensor_logs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_fusion_reports_updated_at ON fusion_reports;
CREATE TRIGGER trg_fusion_reports_updated_at
BEFORE UPDATE ON fusion_reports
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_fusion_report_observations_updated_at ON fusion_report_observations;
CREATE TRIGGER trg_fusion_report_observations_updated_at
BEFORE UPDATE ON fusion_report_observations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_policy_decisions_updated_at ON policy_decisions;
CREATE TRIGGER trg_policy_decisions_updated_at
BEFORE UPDATE ON policy_decisions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_audit_events_updated_at ON audit_events;
CREATE TRIGGER trg_audit_events_updated_at
BEFORE UPDATE ON audit_events
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_policy_decisions_no_delete ON policy_decisions;
CREATE TRIGGER trg_policy_decisions_no_delete
BEFORE DELETE ON policy_decisions
FOR EACH ROW EXECUTE FUNCTION block_policy_decisions_delete();

-- ---------------------------------------------------------------------------
-- Clearance-aware RLS on intelligence tables
-- App must run: SELECT set_config('app.user_clearance', '<LEVEL>', true);
-- ---------------------------------------------------------------------------
ALTER TABLE targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE targets FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS targets_select_policy ON targets;
CREATE POLICY targets_select_policy
ON targets
FOR SELECT
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(canonical_classification)
);

DROP POLICY IF EXISTS targets_insert_policy ON targets;
CREATE POLICY targets_insert_policy
ON targets
FOR INSERT
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(canonical_classification)
);

DROP POLICY IF EXISTS targets_update_policy ON targets;
CREATE POLICY targets_update_policy
ON targets
FOR UPDATE
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(canonical_classification)
)
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(canonical_classification)
);

ALTER TABLE intel_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE intel_observations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS intel_observations_select_policy ON intel_observations;
CREATE POLICY intel_observations_select_policy
ON intel_observations
FOR SELECT
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS intel_observations_write_policy ON intel_observations;
DROP POLICY IF EXISTS intel_observations_insert_policy ON intel_observations;
CREATE POLICY intel_observations_insert_policy
ON intel_observations
FOR INSERT
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS intel_observations_update_policy ON intel_observations;
CREATE POLICY intel_observations_update_policy
ON intel_observations
FOR UPDATE
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
)
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

ALTER TABLE sensor_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE sensor_logs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS sensor_logs_select_policy ON sensor_logs;
CREATE POLICY sensor_logs_select_policy
ON sensor_logs
FOR SELECT
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS sensor_logs_write_policy ON sensor_logs;
DROP POLICY IF EXISTS sensor_logs_insert_policy ON sensor_logs;
CREATE POLICY sensor_logs_insert_policy
ON sensor_logs
FOR INSERT
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS sensor_logs_update_policy ON sensor_logs;
CREATE POLICY sensor_logs_update_policy
ON sensor_logs
FOR UPDATE
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
)
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

ALTER TABLE coordinate_conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE coordinate_conflicts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS coordinate_conflicts_select_policy ON coordinate_conflicts;
CREATE POLICY coordinate_conflicts_select_policy
ON coordinate_conflicts
FOR SELECT
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS coordinate_conflicts_write_policy ON coordinate_conflicts;
DROP POLICY IF EXISTS coordinate_conflicts_insert_policy ON coordinate_conflicts;
CREATE POLICY coordinate_conflicts_insert_policy
ON coordinate_conflicts
FOR INSERT
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS coordinate_conflicts_update_policy ON coordinate_conflicts;
CREATE POLICY coordinate_conflicts_update_policy
ON coordinate_conflicts
FOR UPDATE
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
)
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

ALTER TABLE fusion_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE fusion_reports FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fusion_reports_select_policy ON fusion_reports;
CREATE POLICY fusion_reports_select_policy
ON fusion_reports
FOR SELECT
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS fusion_reports_write_policy ON fusion_reports;
DROP POLICY IF EXISTS fusion_reports_insert_policy ON fusion_reports;
CREATE POLICY fusion_reports_insert_policy
ON fusion_reports
FOR INSERT
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS fusion_reports_update_policy ON fusion_reports;
CREATE POLICY fusion_reports_update_policy
ON fusion_reports
FOR UPDATE
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
)
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

ALTER TABLE policy_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_decisions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS policy_decisions_select_policy ON policy_decisions;
CREATE POLICY policy_decisions_select_policy
ON policy_decisions
FOR SELECT
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS policy_decisions_write_policy ON policy_decisions;
DROP POLICY IF EXISTS policy_decisions_insert_policy ON policy_decisions;
CREATE POLICY policy_decisions_insert_policy
ON policy_decisions
FOR INSERT
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

DROP POLICY IF EXISTS policy_decisions_update_policy ON policy_decisions;
CREATE POLICY policy_decisions_update_policy
ON policy_decisions
FOR UPDATE
USING (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
)
WITH CHECK (
  clearance_to_rank(session_clearance()) >= clearance_to_rank(classification_marking)
);

COMMIT;
