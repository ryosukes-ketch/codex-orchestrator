# Staging Validation Plan

## Purpose
Define the offline-safe-to-staging validation bridge with deterministic evidence and explicit go/no-go gates.

## Baseline (already offline-validated)
- `pytest`/`ruff` quality gates are green (`824 passed, 1 skipped` on 2026-03-30).
- Startup/config matrix behavior is locked for malformed->corrected env flips.
- API/direct parity and retry/event immutability are covered in deterministic tests.
- Protected endpoint actor precedence and 401/403/404/409 mapping are covered offline.

## Staging entry criteria
- [ ] Current mainline commit is pinned and tagged for staging candidate.
- [ ] `.env` for staging is reviewed by operators (no placeholder values).
- [ ] Real credentials are provisioned for selected provider(s).
- [ ] Real auth integration endpoint/issuer metadata is available.
- [ ] Real persistence endpoint (Postgres) is provisioned and reachable from staging.
- [ ] Rollback owner and on-call owner are explicitly assigned.

## Startup / env / secrets checklist (staging)
1. Secrets and config injection
   - Steps:
     - Inject staging env through secret manager (not committed files).
     - Verify required keys are present: `STATE_BACKEND`, `STATE_BACKEND_STRICT`, `DATABASE_URL`, `DEV_AUTH_ENABLED` or auth replacement settings, provider credentials.
   - Pass criteria:
     - Application boot succeeds without fallback surprises.
     - No secret-like values appear in application logs.
   - Human judgment required: yes (secret-source and access review).

2. Boot behavior under strict settings
   - Steps:
     - Start with strict backend/provider settings enabled.
     - Confirm startup behavior is explicit (fail-fast on invalid critical config).
   - Pass criteria:
     - Invalid critical config fails at startup with actionable error.
     - Corrected config starts cleanly.
   - Human judgment required: yes (error clarity and operational acceptability).

## Auth validation plan (staging)
1. Token verification path
   - Steps:
     - Validate missing token, invalid token, expired token, wrong audience, wrong issuer.
     - Validate valid tokens for owner/approver/operator/viewer roles.
   - Pass criteria:
     - Unauthorized requests consistently return `401`.
     - Authenticated-but-forbidden role/actor returns `403`.
     - Audit events capture auth failure and actor resolution.
   - Requires real systems: real auth issuer/keys.

2. Actor authority enforcement
   - Steps:
     - Submit forged body actor with valid bearer token for a different role.
   - Pass criteria:
     - Server-authenticated actor remains authoritative.
     - Body actor tampering is ignored.
   - Human judgment required: low.

## Provider validation plan (staging)
1. Provider routing and fallback
   - Steps:
     - Exercise configured provider aliases and one unsupported provider name.
     - Validate strict-mode behavior and non-strict fallback behavior for the deployment config.
   - Pass criteria:
     - Intended provider path is selected for valid names.
     - Unsupported provider behavior matches policy (fail or fallback).
   - Requires real systems: provider credentials and network path.

2. Provider operational smoke
   - Steps:
     - Run minimal end-to-end orchestration with real provider call path.
   - Pass criteria:
     - Request completes within expected timeout budget.
     - Failure paths are deterministic and operator-actionable.
   - Human judgment required: yes (latency/quality/operational risk).

## Migration / persistence validation plan (staging)
1. Schema/bootstrap readiness
   - Steps:
     - Start app with staging Postgres and strict backend enabled.
     - Validate schema initialization path and permissions.
   - Pass criteria:
     - Startup succeeds without implicit fallback to memory.
     - Read/write/audit retrieval work on persisted records.
   - Requires real systems: Postgres instance and credentials.

2. Persistence lifecycle checks
   - Steps:
     - Run mixed manual flows across fresh app restarts using shared persisted state.
   - Pass criteria:
     - No data loss across restart boundaries.
     - Event ordering and conflict detail remain stable.
   - Human judgment required: medium.

## Manual workflow robustness matrix (staging)
- [ ] approve -> reload -> reject -> revision -> replanning -> resume sequence behaves consistently.
- [ ] mixed actor permutations (owner/approver/viewer/invalid) match expected precedence.
- [ ] API and direct orchestrator paths show matching status/conflict details.
- [ ] safe retries do not duplicate approval/reject/resume/replanning events.
- [ ] note/reason/metadata snapshots remain stable after repeated retries.

## Staging exit criteria (go/no-go)
- [ ] All checklist items pass.
- [ ] No P0/P1 unresolved defects.
- [ ] Rollback rehearsal is completed once against staging config.
- [ ] Human sign-off recorded for auth, provider, and persistence owners.

## Out of scope for staging sign-off
- Production traffic/SLO validation under real peak load.
- Full incident response timing guarantees.
