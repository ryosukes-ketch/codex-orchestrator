# Testing Coverage Summary

## Current Snapshot
- Test result baseline: `824 passed, 1 skipped` (post operational-readiness hardening on 2026-03-30)
- Lint baseline: `ruff check app` and `ruff check tests` passed

## Coverage Areas Completed
1. Deterministic helper seams:
   - pass-through, mapping, composition, boundary/error locking.
2. End-to-end dry-run scenarios:
   - GO/PAUSE/REVIEW journeys and projection/approval-record path behaviors.
3. Higher-level integration:
   - auth + approval policy + repository factory + orchestrator + API interaction.
   - API protected-route error/status mapping and authentication short-circuit behavior.
4. Runtime/manual verification:
   - startup wiring, env-driven auth behavior, protected route behavior, manual resume/reject flows.
   - revision/replanning API mode paths (`replanning`/`rebuilding`/`rereview`) and reset-flag behavior.
   - body-actor tampering hardening across protected manual workflow endpoints.
   - deployment-like startup/config matrices:
     - malformed strict backend -> fail-fast
     - malformed->corrected backend/auth env recovery on fresh app init
     - malformed->corrected provider strict behavior changes on fresh app init
     - postgres non-strict fallback startup with operational route/manual-flow smoke
     - auth-disabled handling with invalid token and deterministic system-actor audit trail
5. Documentation/artifact consistency:
   - cross-reference validity, decision vocabulary alignment, template/example integrity.
6. Dead-code/unreachable audit guards:
   - package export integrity, orphan private helper checks, example reference checks.

## Intentional Gaps (Out of Current Scope)
- Real live external provider execution behavior.
- Production auth/JWT/OIDC validation.
- Database migration lifecycle operations (beyond deterministic repository bootstrap/fallback behavior).
