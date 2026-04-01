# Production Readiness Gaps

## Purpose
Track what is already validated offline versus what still requires staging/live evidence.

## Already offline-validated
- Deterministic startup/config matrix behavior and malformed->corrected env recovery.
- Protected endpoint precedence behavior (401/403/404/409) in offline deterministic tests.
- Shared-repository fresh app/client lifecycle parity for manual flows.
- API/direct parity for conflict detail/status under retry/reload paths.
- Event/note/metadata immutability guarantees in deterministic coverage.

## Staging-only validation needed
1. Real auth integration validation
   - Real token issuer/keys/claim mapping behavior.
   - Revocation/expiry/audience/issuer failure handling.

2. Real provider path validation
   - Credentialed calls, provider latency/error envelopes.
   - Strict/fallback policy behavior under real provider outages.

3. Real persistence deployment validation
   - Postgres connectivity/permissions in staging runtime.
   - Startup strict-mode behavior with live DSN and operational credentials.

4. Operator runbook execution quality
   - Practical execution of staging checklist and evidence capture.

## Production/live validation needed
1. Canary behavior under real traffic
   - Error budget impact and rollback responsiveness.
2. Incident-response execution quality
   - Real escalation timing and triage efficiency.
3. Rollback execution under production controls
   - Proven reversibility within acceptable operational window.
4. Monitoring/alert quality
   - Alert fidelity for auth/provider/persistence/manual workflow regressions.

## Known risks
- Dev-token auth path is not equivalent to production-grade JWT/OIDC validation.
- Provider behavior under live network/provider incidents is unproven.
- Persistence operations are deterministic-tested but not yet validated under real production infrastructure constraints.
- Human operational discipline (checklist execution and escalation speed) is unproven until live drills.

## Non-goals for this campaign
- No architecture redesign.
- No schema rewrite.
- No dependency expansion for new platform components.
- No autonomous live rollout without human sign-off.

## Recommended closure criteria
- Staging checklist completed with explicit owner approvals.
- Live checklist canary phase completed without unresolved P0/P1 issues.
- Rollback rehearsal and incident triage path executed successfully.
- Residual risks documented and accepted by release owner.
