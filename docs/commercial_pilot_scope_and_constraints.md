# Commercial Pilot Scope and Constraints

## Supported pilot profile
- Windows local environment
- PowerShell operator flow
- OpenClaw gateway integration
- SQLite-backed persistence (`STATE_BACKEND=sqlite`)
- Assisted onboarding model (provider-side guidance available)

## Explicitly in-scope
- Readiness gate operation (`scripts\ai_work_system\release-readiness.ps1`)
- Operator lifecycle operation (`scripts\operator-*.ps1`)
- SQLite recovery (`scripts\sqlite-*.ps1`)
- Manifest-first replay and support-bundle handoff

## Explicitly out-of-scope
- Self-serve general availability packaging
- Multi-tenant and high-concurrency scaling validation
- SaaS control plane and billing automation
- OpenClaw upstream internal maintenance
- Broad orchestrator architecture redesign

## Known constraints
1. OpenClaw upstream behavior can affect semantic runtime stability.
2. Strict mode requires completed-only closure; `revision_requested` is not success.
3. External provider credit/auth constraints can block runs even when transport succeeds.
4. SQLite local profile is persistence-focused and not production DB equivalence.

## Operational policy guardrails
- Keep phase_7 strict auth/policy invariants enabled for strict readiness evidence.
- Keep deterministic artifact collection paths for replay/support.
- Use breakglass only with explicit reason/actor evidence.

## Escalation boundaries
- Customer handles runbook first-response steps.
- Provider-side owner handles unresolved provider/auth/runtime semantic blockers.
