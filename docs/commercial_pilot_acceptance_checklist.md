# Commercial Pilot Acceptance Checklist

## Use
Fill this checklist before declaring pilot completion.

## A. Environment and startup
- [ ] Local profile uses `STATE_BACKEND=sqlite`
- [ ] `STATE_BACKEND_STRICT=true` is active
- [ ] Server startup uses `scripts\ai_work_system\start-server.ps1`
- [ ] OpenClaw gateway check passed for target agent/backend

## B. Readiness and strict policy evidence
- [ ] `scripts\ai_work_system\release-readiness.ps1` passed end-to-end
- [ ] Strict policy/auth options were enabled
- [ ] `operator_suite_stage_gate` reports `passed=true`
- [ ] No strict deny reasons in passing evidence

## C. Operator lifecycle evidence
- [ ] Approval cycle reached `completed`
- [ ] Reject-replan cycle reached `completed`
- [ ] Stage telemetry is present
- [ ] `llm_transport_fallbacks` is within policy budget

## D. Persistence and recovery evidence
- [ ] `scripts\sqlite-verify.ps1` passed
- [ ] backup generated via `scripts\sqlite-backup.ps1`
- [ ] restore rehearsal via `scripts\sqlite-restore.ps1` completed (where required)
- [ ] export artifact generated via `scripts\sqlite-export.ps1`

## E. Support readiness evidence
- [ ] `scripts\operator-support-bundle.ps1` package generated
- [ ] `failure-classification.json` includes deterministic category
- [ ] inquiry template is available to customer

## F. Required artifacts attached
- [ ] readiness summary
- [ ] readiness manifest
- [ ] suite bundle manifest
- [ ] suite stage gate report
- [ ] suite handoff envelope
- [ ] support bundle manifest

## G. Final signoff
- Decision: Go / Conditional Go / No-Go
- Decision timestamp:
- Operator signoff:
- Approver signoff:
- Delivery owner signoff:
