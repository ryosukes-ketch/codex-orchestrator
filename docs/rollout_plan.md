# Rollout Plan

## Goal
Move from offline operational readiness to staged/live validation with controlled risk and clear decision gates.

## Scope boundaries
- This plan does not introduce architecture redesign.
- This plan does not approve autonomous live operation without human sign-off.
- This plan assumes current offline baseline is already green.

## Recommended release sequence

1. Readiness freeze (T-7 to T-3)
   - Confirm baseline checks: `pytest`, `ruff app`, `ruff tests`.
   - Freeze non-rollout code changes except critical fixes.
   - Prepare staging/live env manifests and secret references.
   - Output: approved staging candidate build.

2. Staging validation (T-3 to T-1)
   - Execute `docs/staging_validation_plan.md` fully.
   - Record evidence for auth/provider/persistence/manual robustness.
   - Triage defects and apply only scoped fixes.
   - Gate: all required staging checks passed with owner sign-off.

3. Production preflight (T-1 to T0)
   - Execute preflight subset from `docs/live_validation_checklist.md`.
   - Confirm rollback owner + incident commander assignment.
   - Confirm runbook and communication templates are available.
   - Gate: go/no-go meeting with explicit approval.

4. Live canary rollout (T0)
   - Start with controlled traffic/operator paths.
   - Validate auth precedence, provider behavior, persistence stability, and retry immutability.
   - Gate: promote only if no unresolved P0/P1 issues.

5. Progressive rollout (T0+)
   - Expand traffic in bounded increments.
   - Monitor error rates and operator-facing conflict behavior.
   - Keep rollback threshold active through watch window.

6. Stabilization close (T0+watch window)
   - Confirm no critical regressions.
   - Publish rollout result and residual risk list.
   - Archive evidence and decision records.

## Validation tracks and owners
- Auth track:
  - Validate token verification, role mapping, tamper resistance.
  - Owner: security/auth operator.
- Provider track:
  - Validate real provider selection, strictness/fallback policy, failure messaging.
  - Owner: platform/runtime operator.
- Persistence track:
  - Validate postgres strict startup, durability, reload stability.
  - Owner: data/platform operator.
- Manual workflow track:
  - Validate mixed retry paths and API/direct parity under persisted state.
  - Owner: workflow/release operator.

## Decision points
- DP1: staging pass/fail
  - Fail -> block rollout and remediate.
- DP2: production preflight go/no-go
  - Fail -> block rollout, keep current production.
- DP3: canary promote/hold/rollback
  - Promote only on clean metrics and deterministic behavior.
- DP4: post-rollout stabilization close
  - Keep guarded mode until watch window closes.

## Required evidence package
- test/lint baseline output snapshot
- staging checklist completion records
- live checklist completion records
- rollback rehearsal notes
- incident triage contacts and escalation policy

## Non-goals in this sequence
- JWT/OIDC redesign work in rollout window.
- Schema redesign/migration strategy changes during rollout.
- New provider integration architecture during rollout.
