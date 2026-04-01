# Operational Startup Runbook (Offline)

## Purpose
Provide a deterministic offline startup and manual-flow validation sequence before human merge/release decisions.

## Scope
- Offline-safe validation only.
- No live provider calls.
- No production credential validation.

## Required env keys
- `STATE_BACKEND`
- `STATE_BACKEND_STRICT`
- `DATABASE_URL` (only when `STATE_BACKEND=postgres`)
- `TREND_PROVIDER_STRICT`
- `DEV_AUTH_ENABLED`
- `DEV_AUTH_TOKEN_SEED`

## Startup matrix
1. Minimal valid startup
   - `STATE_BACKEND=memory`
   - `STATE_BACKEND_STRICT=false`
   - `TREND_PROVIDER_STRICT=false`
   - `DEV_AUTH_ENABLED=true`
   - Expected:
     - app boots
     - `GET /health` -> `200`
     - protected endpoints require bearer auth

2. Malformed strict backend (fail-fast)
   - `STATE_BACKEND=postgres`
   - `DATABASE_URL` unset
   - `STATE_BACKEND_STRICT` malformed (for example `not-a-bool`)
   - Expected:
     - startup fails with strict backend requirement error

3. Corrected backend/auth recovery
   - Correct to `STATE_BACKEND=memory`
   - set `DEV_AUTH_ENABLED=false`
   - Expected on fresh app init:
     - app boots
     - approval resume can complete without bearer auth

4. Provider strict matrix
   - malformed `TREND_PROVIDER_STRICT` + unknown provider -> `409`
   - corrected `TREND_PROVIDER_STRICT=false` + unknown provider -> mock fallback success

5. Non-strict postgres fallback
   - `STATE_BACKEND=postgres`
   - missing/unavailable DB
   - `STATE_BACKEND_STRICT=false`
   - Expected:
     - app boots via memory fallback
     - core manual approval workflow remains operable

## Manual workflow smoke sequence
1. `POST /orchestrator/run` with external-provider alias (`gemini`) to enter `waiting_approval`.
2. `POST /orchestrator/resume/approval` under expected auth mode.
3. Verify `GET /projects/{project_id}/audit` event integrity:
   - actor resolution recorded
   - no duplicate approval/retry events on safe retries
   - conflict detail remains deterministic for rejected/non-pending retry branches

## Offline gates
- `python -m pytest -q tests`
- `python -m ruff check app`
- `python -m ruff check tests`

## Still requires live validation
- real provider credentialed execution
- production authn/authz rollout (JWT/OIDC)
- production database migration/rollback operations
- deployment/traffic/runtime SLO validation
