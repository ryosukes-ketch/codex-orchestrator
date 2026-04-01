# Rollback Checklist

## Purpose
Define deterministic rollback actions and decision thresholds for staging/live rollout issues.

## Rollback triggers
- [ ] Auth bypass, privilege escalation, or actor-authority violation risk.
- [ ] Persistent 5xx errors affecting protected/manual workflow endpoints.
- [ ] Data consistency risk in approval/revision/replanning/retry flows.
- [ ] Provider failure mode causing unsafe operator decisions.
- [ ] Unknown startup/recovery behavior under production config.

## Immediate triage checklist (first 15 minutes)
- [ ] Declare incident severity and assign incident commander.
- [ ] Freeze further rollout progression.
- [ ] Capture current deployment version/config hash.
- [ ] Capture key logs/metrics around auth/provider/persistence/manual endpoints.
- [ ] Decide rollback-now vs hold-and-investigate using threshold policy.

## Rollback execution checklist
1. Traffic and release controls
   - [ ] Stop traffic increase.
   - [ ] Route traffic to previous stable release target.

2. Config/secret rollback
   - [ ] Revert to last known-good config bundle.
   - [ ] Revert secret references only through approved secret manager path.

3. Runtime verification after rollback
   - [ ] Verify app startup and `/health`.
   - [ ] Verify protected endpoint auth behavior.
   - [ ] Verify one manual workflow smoke (run -> approval/reject path).

4. Persistence safeguards
   - [ ] Confirm no in-progress destructive persistence operation is left partial.
   - [ ] Validate recent persisted records are still queryable.

## Rollback success criteria
- [ ] Error rate returns to pre-rollout baseline.
- [ ] Protected/manual workflows behave as pre-rollout.
- [ ] No unresolved data integrity alarm remains.

## Human decision checkpoints
- [ ] Incident commander approves rollback trigger.
- [ ] Release owner approves rollback completion.
- [ ] Service owner approves re-entry criteria before next rollout attempt.

## Post-rollback actions
- [ ] Record timeline, root-cause hypothesis, and affected scope.
- [ ] Open corrective action items with owner/date.
- [ ] Update rollout plan gates if threshold policy proved insufficient.
