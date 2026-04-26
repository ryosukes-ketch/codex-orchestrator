# AI company orchestrator commercial auth productization

## Objective
Deliver a production-grade authentication baseline for the AI company orchestrator without regressing strict approval/policy/audit behavior.

## Why this is a separate objective
- `steady_state` remains completed and preserved as operations mode.
- This work changes auth/approval behavior and is intentionally handled outside steady-state incremental operations.

## Scope
1. Replace or abstract `DevTokenAuthService` for production-oriented auth validation.
2. Preserve operator/approver evidence fields in all protected flows.
3. Keep strict policy behavior unchanged:
   - completed-only strict success
   - no relaxation of auth/policy assertions
4. Preserve existing API flow contracts:
   - run / approval resume / reject / revision / replanning / audit
5. Update docs, tests, and staging evidence together.

## Out of scope
- Provider expansion
- Architecture rewrite
- UI overhaul
- New phase creation in roadmap
- Relaxing strict policy/auth gates

## Required guardrails
- Never trust client actor identity when server-authenticated identity is available.
- Keep deny reasons auditable.
- Keep approval and authorization decision paths test-covered.
- No secret files or real credential material committed.

## Implementation batches (proposed)
### Batch 1: auth abstraction seam
- Introduce explicit auth interface and runtime binding seam.
- Keep existing behavior fully backward compatible under dev profile.

### Batch 2: production auth mode
- Add production auth validation mode (config-driven).
- Keep explicit auth source/mode evidence in audit.

### Batch 3: approval/auth hardening verification
- Add/extend tests for operator/approver boundary and failure mapping.
- Verify protected routes preserve existing behavior and evidence.

### Batch 4: documentation and evidence closure
- Update startup/readiness/operator runbooks.
- Record representative pass/fail evidence in staging execution record.

## Acceptance criteria
- Protected routes validate identity via non-dev mode when configured.
- Operator/approver role evidence remains visible in audit/history.
- Strict policy behavior remains unchanged.
- Existing approval/reject/revise/replan/audit flow tests pass.
- Docs and evidence are synchronized.

## Stop conditions (REVIEW)
- Any DB migration becomes necessary.
- Any strict policy relaxation is requested.
- New dependency is required for token verification and has no approved alternative.
- External identity provider contract changes are required.
