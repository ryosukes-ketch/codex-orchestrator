# Pre-Production Requirements

## Purpose
Define mandatory conditions before staging and live rollout decisions.

## Staging preconditions
1. Startup/config validity
   - Strict/non-strict backend/provider behavior must match documented policy.
   - Malformed-to-corrected environment transitions must recover on fresh app init.
2. Auth validation
   - Real token issuer/claims path must be verified (missing/invalid/expired/forbidden).
   - Actor tampering must remain non-authoritative.
3. Provider validation
   - Real provider routing, failure messaging, and strictness behavior must be validated.
4. Persistence validation
   - Real persistence startup/connectivity and durable reload behavior must be validated.
5. Manual workflow validation
   - Mixed approve/reject/revision/replanning/retry flows must remain parity-stable.
6. Rollback and incident readiness
   - Rollback trigger and execution checklist must be rehearsed once in staging.

## Live-entry requirements
1. Staging sign-off completed by responsible owners.
2. Preflight and canary checklist completed with explicit go/no-go decision.
3. Monitoring, incident channel, and rollback owner assignments active.
4. No unresolved P0/P1 defects in auth/provider/persistence/manual-flow paths.

## Human judgment required
- Canary promotion decision.
- Auth claim mapping acceptance.
- Provider behavior acceptance under real failures.
- Rollback invocation timing.

## Required documents
- `docs/staging_validation_plan.md`
- `docs/live_validation_checklist.md`
- `docs/rollout_plan.md`
- `docs/rollback_checklist.md`
- `docs/production_readiness_gaps.md`
