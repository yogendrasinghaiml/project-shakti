# SHAKTI Auth Secret Rotation Runbook

## Scope

This runbook defines how to rotate shared secrets used for signed gateway auth claims:

- `AUTH_SHARED_SECRET_PRIMARY`
- `AUTH_SHARED_SECRET_SECONDARY`
- `AUTH_SHARED_SECRETS_FILE` (JSON source of `primary` and `secondary`)

It also defines replay-guard requirements for production deployments.

## Preconditions

1. Persistent replay guard must be enabled:
   - `AUTH_REQUIRE_PERSISTENT_REPLAY_GUARD=true`
2. Database migration including `auth_claim_replay_guard` must be applied.
3. Gateway and service clocks must be NTP-synchronized.
4. New secret must be generated from a CSPRNG and stored in a secret manager.

## Secrets File Format

If using `AUTH_SHARED_SECRETS_FILE`, provide JSON with this shape:

```json
{
  "primary": "new-active-secret",
  "secondary": "old-acceptance-secret"
}
```

Rules:

1. `primary` is used by the gateway to sign new claims.
2. `secondary` is accepted by the service during overlap/cutover.
3. Set `secondary` to empty after full cutover.

## Rotation Procedure

### Phase 1: Prepare

1. Generate `new_secret`.
2. Keep current secret as `old_secret`.
3. Update secret manager entry (or secrets file) so:
   - `primary = new_secret`
   - `secondary = old_secret`

### Phase 2: Deploy

1. Deploy gateway reading updated secrets and signing with `primary`.
2. Deploy SHAKTI service reading same updated secrets.
3. Verify both old and new signed tokens are accepted during overlap window.

### Phase 3: Cutover

1. Wait at least `AUTH_MAX_SKEW_SECONDS + AUTH_REPLAY_TTL_SECONDS`.
2. Remove old secret from acceptance set:
   - `secondary = ""`
3. Redeploy gateway/service with updated configuration.

### Phase 4: Verify

1. Positive test: token signed by `primary` succeeds.
2. Negative test: token signed by retired secret fails with 401.
3. Replay test: same token (`jti`) reused twice returns 401 on second use.

## Rollback

1. If auth failures spike after rotation, restore previous pair:
   - `primary = old_secret`
   - `secondary = new_secret`
2. Redeploy gateway/service.
3. Investigate clock skew, config propagation, and secret distribution drift.

## Operational Checks

1. Monitor 401 rates for:
   - Invalid signature
   - Timestamp outside skew
   - Replay detected
2. Alert if replay-guard table growth exceeds expected TTL behavior.
3. Periodically prune/monitor `auth_claim_replay_guard` index health.

