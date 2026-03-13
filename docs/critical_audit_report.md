# SHAKTI Critical Audit - Logical Gaps and Remediations

## Scope

Audit performed on Phase 2-4 artifacts:

- `db/migrations/0001_phase2_foundation.up.sql`
- `backend/intelligence_fusion_service.py`
- `frontend/TacticalMapView.tsx`

## Findings and Fixes

1. Missing clearance protection on conflict-read APIs
- Risk: A caller could query pending conflicts without any clearance gate in service logic.
- Fix: Added mandatory `X-User-Clearance` enforcement for all `/v1/*` routes and clearance-propagated repository queries.

2. Incomplete conflict classification propagation
- Risk: Conflict objects had no explicit classification marking, making downstream access control ambiguous.
- Fix: Added `classification_marking` to `coordinate_conflicts`, indexed it, surfaced it in API model, and enforced classification-aware reads.

3. Non-idempotent migration behavior for triggers
- Risk: Re-running schema migration could fail with duplicate trigger errors.
- Fix: Added `DROP TRIGGER IF EXISTS ...` prior to trigger creation for all auditable tables.

4. Policy audit trail not append-only at DB layer
- Risk: `policy_decisions` could be deleted directly, violating legal traceability guarantees.
- Fix: Added `block_policy_decisions_delete()` and a `BEFORE DELETE` trigger to hard-block deletes.

5. Missing RLS on sensitive derived tables
- Risk: `coordinate_conflicts`, `fusion_reports`, and `policy_decisions` lacked row-level clearance controls.
- Fix: Enabled and forced RLS with clearance-ranked select/write policies for all three tables.

6. Missing FK integrity from observations to sensor registry
- Risk: `intel_observations.sensor_id` could reference non-existent sensors.
- Fix: Added idempotent FK constraint `intel_observations_sensor_fk`.

7. Race window in target conflict detection
- Risk: Concurrent ingests for same `target_id` could bypass reliable conflict checks.
- Fix: Added `pg_advisory_xact_lock(hashtextextended(target_id, 0))` to serialize per-target conflict evaluation.

8. Unbounded ingest request size
- Risk: Payload-size abuse could cause memory pressure and service degradation.
- Fix: Added configurable `MAX_INGEST_BYTES` guard with `413` rejection.

9. Weak write attribution requirement
- Risk: Write endpoints accepted missing/invalid actor identity, weakening non-repudiation.
- Fix: Added mandatory `X-User-Id` UUID validation for write methods.

10. External map tile dependency in tactical UI
- Risk: Default external tile source introduces outbound dependency and telemetry leakage.
- Fix: Switched default tile URL to local cache path (`/tiles/{z}/{x}/{y}.png`) and made it configurable.

11. Time-slider stale bounds after data refresh
- Risk: New event datasets could leave stale slider bounds, causing incorrect map filtering.
- Fix: Added reactive bounds reset on event timeline changes.

## Validation Status

- Python syntax validation: passed via `py_compile`.
- Backend linting: passed via `ruff check backend`.
- Backend type checking: passed via `mypy` against `backend/intelligence_fusion_service.py`.
- Frontend helper tests: passed via `node --test frontend/tactical_helpers.test.mjs`.
- Backend pytest suite: `39 passed, 5 skipped` with live PostgreSQL integration gated behind explicit opt-in.
- Live PostgreSQL integration suite: passed via `npm run test:backend:integration` against `docker-compose.test.yml` (`5 passed`).
