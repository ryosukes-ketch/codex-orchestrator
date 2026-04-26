# Commercial Launch Go/No-Go Checklist

Use this checklist for launch decision on each release unit.

## Inputs
- release notes artifact (based on `docs/release_notes_template.md`)
- known issues snapshot (`docs/known_issues_register.md`)
- readiness/support manifests and incident evidence

## Launch acceptance checklist

### Runtime and policy gates
- [ ] readiness command evidence exists for target release window.
- [ ] strict policy/auth assertions are present in evidence bundle.
- [ ] no unresolved policy/auth boundary violation blocks launch.

### Persistence and recovery
- [ ] sqlite backup/restore/export/replay paths are validated or explicitly waived with rationale.
- [ ] rollback checklist is current and references the active release unit.
- [ ] rollback signal and trigger rationale are recorded.

### Support readiness
- [ ] support boundary roles and escalation path are confirmed:
  - `docs/commercial_launch_support_boundary.md`
- [ ] SLA-lite severity and response expectations are applied:
  - `docs/commercial_launch_sla_lite.md`
- [ ] support-safe package artifacts are present for representative run.

### Release documentation
- [ ] release notes are completed for the release unit.
- [ ] known issues register is updated for this decision cycle.
- [ ] staging execution record contains launch-readiness trace.

## Decision rubric
- `GO`
  - all critical checks pass
  - no unresolved `P1` issue
  - rollback path is validated and evidence-linked
- `PAUSE`
  - one or more critical checks incomplete
  - unresolved issues require mitigation before launch
- `REVIEW`
  - risk exceeds defined ownership boundaries
  - policy/auth or phase/governance direction requires human decision

## Decision record
- decision:
- rationale:
- release owner:
- timestamp (UTC):
- linked evidence paths:
