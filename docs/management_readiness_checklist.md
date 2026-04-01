# Management Readiness Checklist

## Purpose
Provide a minimal self-check for whether the repository has required artifacts for safe Management Department review operations.

This checklist supports readiness assessment only. It does not trigger operations.

## Readiness checks (minimum)

### 1) Governance baseline files
- [ ] `AGENTS.md` exists and is current.
- [ ] `docs/direction_guard.json` exists.
- [ ] `docs/roadmap.json` exists.

### 2) Management review artifacts
- [ ] `CurrentBriefArtifact` / compatible artifact path is available.
- [ ] `ManagementReviewPacket` structure is available.
- [ ] `docs/management_review_template.md` exists.
- [ ] `docs/review_decision_template.md` exists.

### 3) Queue and decision recording artifacts
- [ ] `ReviewQueueItem` structure exists.
- [ ] `docs/review_queue_format.md` exists.
- [ ] `ManagementDecisionRecord` structure exists.
- [ ] `docs/management_decision_format.md` exists.
- [ ] queue and decision examples exist under `docs/examples/`.

### 4) Dry-run management path
- [ ] dry-run orchestration helper exists (`run_dry_run_orchestration`).
- [ ] dry-run output includes management-facing summary/projection fields.
- [ ] dry-run path remains non-authoritative for risky continuation.

### 5) Model governance policy
- [ ] `docs/model_governance_policy.md` exists.
- [ ] `docs/model_routing_policy.json` exists.
- [ ] latest-alias usage boundaries are explicit.

## Operational interpretation
- If any check above fails, mark readiness as `PAUSE` and fix missing artifacts first.
- If hard-gate-related artifacts are missing, mark readiness as `REVIEW`.
- Readiness `GO` means artifact prerequisites are present, not that runtime changes are approved.

## Suggested cadence
- Run checklist before major continuation cycles.
- Re-check after adding new management/review artifacts.

## Pre-operation readiness gate (limited operations)

### 1) Ready for dry-run use
Dry-run use is allowed when:
- sections 1 through 5 above are complete
- `docs/examples/management_review_flow_example.md` is present and current
- dry-run outputs are treated as simulation artifacts only (non-authoritative)

### 2) Ready for limited management-review operations
Limited operations may begin only when all are true:
- Management Department reviewer is explicitly assigned (human or stronger management model)
- review packet -> review queue -> management decision recording flow is available
- Action Department output is treated as advisory only
- hard-gate-first review remains enforced for every non-trivial item

Allowed limited operations:
- repository-side review packet/queue/decision preparation
- docs/test/local validation tasks with explicit `GO` and no hard-gate trigger

### 3) Not ready for live autonomous continuation
Live autonomous continuation is not approved yet.

Blocked conditions include:
- `required_review=true`
- any hard gate trigger is active
- governance-sensitive scopes (auth/approval/policy/audit/schema/dependency/security/direction)

Not approved for live integration:
- external provider live calls as default operational path
- automatic execution based only on latest-alias or cheap action-model suggestions

Mock/stub only at this stage:
- trend/provider operational use remains mock/stub-first unless explicitly reviewed
- dry-run management flow artifacts remain simulation support, not live control plane

### 4) Mandatory REVIEW triggers before real operations
Return `REVIEW` and block operations when:
- roadmap phase or architecture direction must change
- dependency or migration is required
- auth/approval/policy/audit semantics may change
- cross-department ambiguity affects safe routing
- verification is unstable and root cause is unclear

### 5) Human approval checkpoints
Human/management approval is mandatory:
- before moving from dry-run-only readiness to limited management-review operations
- for any queue item with hard-gate trigger or `REVIEW` recommendation
- before any action implying external send, destructive change, bulk modify, or production impact

### 6) Deferred backlog before live integration
Before any live autonomous continuation approval, complete at least:
- stronger authn rollout (planned JWT/OIDC path)
- policy operations hardening and auditability improvements
- migration from mock/stub-first provider usage to reviewed live-provider contracts
- explicit live-operation runbook and rollback validation criteria

## Action Department limited-live provider activation gate

### 1) Preconditions for limited live provider use
Limited live provider use for Action Department may be considered only when all are true:
- governance baseline + model governance checks (sections 1-5) are complete
- pre-operation readiness gate for limited operations is satisfied
- hard-gate-first routing is active for every non-trivial task
- provider adapters remain the only allowed integration boundary

Clarification:
- limited live provider use is not equal to autonomous continuation
- management approval is required governance input, not automatic execution permission

### 2) Human approval checkpoints before activation
- explicit Management Department approval to activate limited live provider use
- explicit approval scope (allowed task types, departments, and guardrails)
- explicit stop/rollback owner assignment before activation

### 3) Required validation already completed
- mock/stub workflow validation is complete for the same task shape
- management review flow artifacts are validated as cross-consistent
- recommendation and escalation paths are verified in dry-run documentation/tests

### 4) Required artifacts and handoff structures present
Activation is blocked unless all are present and current:
- management review packet artifact shape
- review queue item artifact shape
- management decision record artifact shape
- management prompt and runbook guidance for GO/PAUSE/REVIEW

### 5) Blockers that prevent activation
Do not activate limited live provider use when any applies:
- hard gate trigger is active for intended scope
- ambiguous cross-department ownership remains unresolved
- latest-alias outputs are being treated as approval authority
- required review/queue/decision handoff artifacts are missing or stale
- rollback/disable procedure is undefined

### 6) Rollback / disable expectations
If any guardrail fails after activation:
- immediately disable limited live provider use and fall back to mock/stub path
- route affected work to `REVIEW` with explicit escalation reason
- record management decision and constraints before any re-activation attempt

### 7) Deferred work still required before broader live use
Before broader (non-limited) live provider use:
- complete stronger authn and policy operations hardening backlog
- define and verify live-provider incident runbook with rollback drills
- demonstrate stable governance/audit behavior under repeated limited-live cycles
- document explicit criteria for expanding beyond Action Department limited scope
