# Live Validation Checklist

## Purpose
Provide a production/live validation checklist after staging pass, focused on controlled rollout safety.

## Preconditions (must be true)
- [ ] Staging validation completed and signed off.
- [ ] Rollback checklist reviewed by on-call + release owner.
- [ ] Incident channel and escalation tree are active.
- [ ] Metrics/logging dashboards for auth/provider/persistence are ready.

## Live rollout checklist

### Phase 1: pre-traffic validation
- [ ] Deploy candidate artifact/config to production environment with traffic disabled.
- [ ] Confirm app boots with production env/secret injection.
- [ ] Verify `/health` and one protected endpoint behavior with controlled credentials.
- Pass criteria:
  - Boot completes without unexpected fallback.
  - Protected endpoint returns expected auth outcome.

### Phase 2: canary validation
- [ ] Enable limited traffic (or controlled operator-only traffic).
- [ ] Run canary workflow set:
  - [ ] orchestrator run requiring approval
  - [ ] approval resume success and forbidden cases
  - [ ] reject -> revision -> replanning start path
- Pass criteria:
  - No unexpected 5xx spikes.
  - 401/403/404/409 precedence matches expected behavior.
  - Event/note/metadata stability holds for retries.
- Human judgment required: yes (canary risk acceptance).

### Phase 3: auth validation in live
- [ ] Validate real token claims mapping (owner/approver/operator/viewer).
- [ ] Validate revoked/expired token behavior.
- [ ] Validate actor tampering remains non-authoritative.
- Pass criteria:
  - Auth failures are deterministic and auditable.
  - No cross-role privilege escalation observed.

### Phase 4: provider validation in live
- [ ] Validate selected live provider path with real credentials.
- [ ] Validate strict/fallback behavior matches configured policy.
- [ ] Validate operator-visible error messaging for provider faults.
- Pass criteria:
  - Provider failures are actionable and non-ambiguous.
  - No silent fallback contrary to strict policy.

### Phase 5: persistence validation in live
- [ ] Validate persisted project lifecycle across app restarts.
- [ ] Validate approval/revision/replanning retries against persisted state.
- [ ] Validate audit retrieval consistency.
- Pass criteria:
  - No duplicate/reordered critical events for safe retries.
  - Conflict-detail and status responses remain consistent.

## Stop / rollback triggers
- [ ] Unexpected auth bypass or privilege drift.
- [ ] Persistent 5xx or data inconsistency in manual flow paths.
- [ ] Provider failures causing unsafe operator decisions.
- [ ] Persistence corruption risk or rollback uncertainty.

## Live completion criteria
- [ ] Canary window passes with no unresolved P0/P1 incidents.
- [ ] Production operator checklist sign-off is recorded.
- [ ] Post-rollout monitoring watch window closes cleanly.

## Items requiring explicit human/operator judgment
- Canary promotion decision.
- Auth claim mapping correctness acceptance.
- Provider quality/latency acceptability.
- Rollback invocation timing.
