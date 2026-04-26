# Commercial Launch Support Boundary and Escalation Matrix

## Purpose
Define launch-phase ownership boundaries so incidents are routed deterministically with auditable escalation.

## Scope
- Applies to customer-managed self-serve environments using phase_10 and phase_11 packaging artifacts.
- Preserves strict completed-only semantics and phase_7 through phase_11 policy invariants.

## Role ownership

| Role | Core responsibility | Out of scope |
| --- | --- | --- |
| `operator` | Runs startup/readiness flows, collects first-response evidence, executes documented scripts. | Policy override decisions, release approval authority. |
| `approver` | Approves/rejects protected approval flow and enforces strict approval boundary. | Runtime troubleshooting without evidence package. |
| `admin` | Environment/config ownership (runtime host, process management, storage path, secrets placement). | Business release go/no-go decisions. |
| `product_owner` | Release decision authority (`GO`/`PAUSE`/`REVIEW`) based on evidence and risk. | Direct infrastructure remediation. |
| `support_owner` | Incident coordination, severity classification, escalation tracking, customer communication cadence. | Ad hoc policy relaxation. |

## Responsibility split by failure domain

| Domain | Primary owner | Secondary owner | Required first evidence |
| --- | --- | --- | --- |
| local config/runtime startup | `admin` | `operator` | preflight output, startup command, readiness summary |
| OpenClaw gateway/runtime | `admin` | `support_owner` | gateway check output, readiness manifest, stage report |
| provider auth/quota/upstream access | `admin` | `support_owner` | failure classification (`provider_auth`), auth probe output |
| policy/auth boundary failures | `approver` | `product_owner` | audit assert output, stage gate report, deny reasons |
| persistence/restore/export (sqlite) | `admin` | `operator` | sqlite verify/backup/export reports, restore evidence |
| workflow/lifecycle mismatches | `support_owner` | `operator` | status/audit/stage-report replay artifacts |

## Escalation triggers
- Escalate to `support_owner` immediately when:
  - failure classification is `policy`, `provider_auth`, or `persistence_restore`
  - incident severity is `P1`
  - customer-visible outage exceeds SLA-lite first-response target
- Escalate to `product_owner` when:
  - rollback signal becomes `rollback_recommended` or `rollback_required`
  - known issue status changes to `accepted_risk` for launch decision context
  - repeated `P2` issue occurs 3+ times in a 7-day window
- Escalate to `approver` when:
  - strict-mode auth role evidence is missing/mismatched
  - breakglass traceability requirements are violated

## Escalation package minimum
- `support-bundle.manifest.json`
- `failure-classification.json` and `failure-classification.md`
- `support-intake.manifest.json`
- command transcript (exact command, timestamp, actor)
- source manifest path (`readiness-manifest-*.json` or `bundle-manifest.json`)

## Deterministic escalation path
1. `operator` gathers evidence using support-safe scripts.
2. `support_owner` assigns severity and confirms owner domain.
3. Domain owner performs mitigation or rollback recommendation.
4. `product_owner` issues launch/governance decision (`GO`/`PAUSE`/`REVIEW`).
5. Outcome is recorded in:
   - `docs/known_issues_register.md`
   - `docs/staging_execution_record.md`
   - release notes artifact for the release unit
