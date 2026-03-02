# SHAKTI Release Runbook

## Scope
This runbook defines the standard branch, merge, tag, and rollback process for SHAKTI.

## Standard Release Flow
1. Create a feature branch from `main`.
   - Example: `git checkout -b codex/<short-change-name>`
2. Make changes, commit, and push the branch.
3. Open a PR to `main`.
4. Wait for required check `release-gate` to pass.
5. Merge the PR to `main`.
6. Tag the release commit with an annotated semantic tag and push it.
   - Example:
     - `git checkout main && git pull --ff-only`
     - `git tag -a vX.Y.Z -m "SHAKTI vX.Y.Z"`
     - `git push origin vX.Y.Z`

## Post-Release Verification
1. Confirm local status is clean:
   - `git status --short --branch`
2. Confirm tag exists locally:
   - `git tag -l "vX.Y.Z"`
3. Confirm tag exists on remote:
   - `git ls-remote --tags origin refs/tags/vX.Y.Z refs/tags/vX.Y.Z^{}`

## Rollback Options
### Option A: Revert bad merge commit (preferred)
1. Create rollback branch from `main`:
   - `git checkout -b codex/rollback-<date> main`
2. Revert the merge commit:
   - `git revert -m 1 <bad_merge_sha>`
3. Push and open PR to `main`.
4. Merge after `release-gate` passes.
5. Tag rollback release:
   - `git tag -a vX.Y.Z+rollback1 -m "Rollback for vX.Y.Z"`
   - `git push origin vX.Y.Z+rollback1`

### Option B: Restore from known-good tag
1. Create branch from good tag:
   - `git checkout -b codex/restore-<date> <good_tag>`
2. Push and open PR to `main`.
3. Merge after `release-gate` passes.
4. Tag new restored release.
