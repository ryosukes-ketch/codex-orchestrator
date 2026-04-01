# Acceptance Criteria

## Purpose
Define concise pass/fail gates for requirements-freeze readiness from code logic through live-validation entry.

## AC-1 Code and logic readiness (offline)
- Pass criteria:
  - Core dry-run orchestration artifacts are generated deterministically from intake to handoff.
  - GO/PAUSE/REVIEW projection behavior remains stable.
  - Unknown helper mapping values raise `KeyError` where behavior is contract-locked.
  - Approval/revision/retry paths keep API/direct parity under repository-backed reload scenarios.
  - `pytest` and `ruff` are green in offline CI/local validation.
- Fail criteria:
  - Contract drift in artifact fields, decision projection semantics, or helper-chain boundary behavior.
  - Determinism or parity regressions in protected/manual-flow paths.

## AC-2 Offline operational readiness
- Pass criteria:
  - Startup/config behavior is deterministic for valid and malformed-to-corrected env sequences.
  - Auth/dependency/runtime binding recovery paths are stable across fresh app/client lifecycles.
  - Event ordering and note/metadata immutability locks remain green in offline tests.
  - Runbook/checklist docs exist and align with tested behavior.
- Fail criteria:
  - Startup recovery ambiguity, cache leakage, or mismatched runbook instructions.

## AC-3 Staging entry criteria
- Pass criteria:
  - `docs/staging_validation_plan.md` steps are executable by operators end-to-end.
  - Auth/provider/persistence checks are assigned to owners and include explicit pass/fail outcomes.
  - Rollback drill procedure and incident handoff path are ready before staging go.
- Requires human judgment:
  - Provider behavior acceptance under real credentials/failures.
  - Auth claims/role mapping acceptance in staging identity environment.
- Fail criteria:
  - Missing owner for critical validation, ambiguous acceptance threshold, or incomplete rollback rehearsal.

## AC-4 Live validation entry criteria
- Pass criteria:
  - Staging validation is completed with documented sign-off.
  - `docs/live_validation_checklist.md` preflight and go/no-go decision are completed.
  - Rollback decision points and incident command chain are confirmed.
  - No unresolved P0/P1 issues in auth/provider/persistence/manual-flow core paths.
- Requires human judgment:
  - Canary promotion decisions and rollback trigger timing.
  - Production risk acceptance for residual non-blocking issues.
- Fail criteria:
  - Missing staging evidence, unresolved high-severity risks, or undefined rollback authority.

## Validation scope boundary
- Offline-validated now:
  - Deterministic code behavior and traceable artifact composition.
- Staging-validated later:
  - Real auth/provider/persistence behavior under controlled live-like conditions.
- Live-validated later:
  - Production rollout safety under real traffic and operational pressure.
