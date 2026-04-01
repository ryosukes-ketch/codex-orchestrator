# Manual Verification Checklist

Use this checklist before release sign-off and immediately after deployment in a controlled environment.

## Pre-Release
- [ ] Confirm local quality gates are green:
  - [ ] `python -m pytest -q tests`
  - [ ] `python -m ruff check app`
  - [ ] `python -m ruff check tests`
- [ ] Confirm `.env.example` uses placeholders only (no real secrets).
- [ ] Confirm `STATE_BACKEND` expectations are documented for `memory` and `postgres`.

## Startup / API Wiring
- [ ] Start API with `uvicorn app.api.main:app --reload`.
- [ ] Verify `GET /health` returns 200.
- [ ] Verify minimal startup env works (`STATE_BACKEND=memory`, `DEV_AUTH_ENABLED=true`, `TREND_PROVIDER_STRICT=false`).
- [ ] Verify malformed->corrected startup env recovery:
  - [ ] malformed strict backend (`STATE_BACKEND=postgres`, missing `DATABASE_URL`, malformed `STATE_BACKEND_STRICT`) fails fast
  - [ ] corrected backend/auth env boots cleanly on next app init
- [ ] Verify malformed `TREND_PROVIDER_STRICT` behaves strict (unknown provider returns `409`) and corrected value restores fallback behavior.
- [ ] Verify protected approval/revision endpoints require bearer auth when `DEV_AUTH_ENABLED=true`.
- [ ] Verify protected approval/revision endpoints allow operation without bearer auth when `DEV_AUTH_ENABLED=false`.
- [ ] Verify actor identity is resolved server-side (body actor fields are non-authoritative).

## Manual Workflow
- [ ] Run `POST /orchestrator/run` with `trend_provider=gemini` and verify `waiting_approval`.
- [ ] Verify approval resume path works for authorized actor and fails for unauthorized actor.
- [ ] Verify rejection path moves project to `revision_requested`.
- [ ] Verify revision resume path works for `replanning` / `rebuilding` / `rereview`.
- [ ] Verify audit endpoint records authentication/authorization/approval events.

## Governance / Documentation
- [ ] Confirm GO/PAUSE/REVIEW terminology is consistent across README/runbooks.
- [ ] Confirm docs/examples/templates referenced in README/docs exist.
- [ ] Confirm release notes include residual risks and out-of-scope items.
- [ ] Confirm `docs/operational_startup_runbook.md` matrix still matches validated startup behavior.
- [ ] Confirm rollout prep artifacts are present and current:
  - [ ] `docs/staging_validation_plan.md`
  - [ ] `docs/live_validation_checklist.md`
  - [ ] `docs/rollout_plan.md`
  - [ ] `docs/rollback_checklist.md`
  - [ ] `docs/production_readiness_gaps.md`
- [ ] Confirm runbook/checklist clearly separates offline-validated scope vs live-validation-required scope.
