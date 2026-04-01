# Staging Evidence Template

## Purpose
Define what evidence to capture during staging so go/no-go decisions are auditable.

## Evidence package metadata
- Evidence package ID:
- Execution ID:
- Candidate version/tag:
- Commit SHA:
- Collection owner:
- Storage location:
- Retention owner:

## Evidence categories

### 1. Startup
- Capture:
  - startup command/config profile used
  - boot success/failure logs
  - `/health` response evidence
- Minimum evidence:
  - timestamped startup log excerpt
  - health check output snapshot
- Acceptance evidence checklist:
  - [ ] No unexpected fallback behavior
  - [ ] Startup errors are actionable if present

### 2. Auth
- Capture:
  - missing/invalid/expired token outcomes
  - role-based allowed/forbidden outcomes
  - actor-tampering attempt outcome
- Minimum evidence:
  - protected endpoint request/response samples (sanitized)
  - auth failure/success logs with correlation IDs
- Acceptance evidence checklist:
  - [ ] 401/403 behavior is deterministic
  - [ ] Server-authenticated actor authority is preserved

### 3. Provider
- Capture:
  - provider selection behavior
  - strict/fallback behavior under configured policy
  - provider failure messaging behavior
- Minimum evidence:
  - provider path invocation log snippets
  - representative success/failure response snapshots
- Acceptance evidence checklist:
  - [ ] Selected provider path is correct
  - [ ] Failure messaging is operator-actionable

### 4. Persistence
- Capture:
  - persisted write/read lifecycle evidence
  - restart/reload continuity evidence
  - audit retrieval consistency evidence
- Minimum evidence:
  - restart-boundary before/after state snapshots
  - audit endpoint output samples
- Acceptance evidence checklist:
  - [ ] No unexpected state loss across restarts
  - [ ] Persisted state is reload-consistent

### 5. Manual workflow
- Capture:
  - mixed approve/reject/revision/replanning/retry runs
  - API/direct parity checks on same persisted project
  - event ordering and conflict-detail consistency
- Minimum evidence:
  - workflow timeline logs
  - API/direct comparison records
- Acceptance evidence checklist:
  - [ ] No duplicate/reordered critical events on safe retry
  - [ ] Notes/metadata snapshots remain stable

### 6. Rollback
- Capture:
  - rollback rehearsal trigger condition
  - rollback execution steps and outcome
  - post-rollback health and data integrity checks
- Minimum evidence:
  - rollback procedure execution record
  - post-rollback verification outputs
- Acceptance evidence checklist:
  - [ ] Rollback can be executed within expected window
  - [ ] Post-rollback service state is acceptable

## Evidence quality gates
- [ ] All artifacts are timestamped.
- [ ] Sensitive values are redacted/sanitized.
- [ ] Links are valid and accessible to reviewers.
- [ ] Each critical check has at least one primary evidence item.

