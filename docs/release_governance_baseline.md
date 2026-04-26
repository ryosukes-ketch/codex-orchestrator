# Release Governance Baseline

## Purpose
Define a deterministic release-governance contract for phase_11 launch readiness without changing auth, approval, or policy invariants.

## Scope and invariants
- Keep strict completed-only behavior and all phase_7 through phase_10 policy guarantees.
- Treat release governance as packaging/operations control, not architecture redesign.
- Keep sqlite recovery/support-safe evidence workflows compatible with existing runbooks.

## Release unit contract
Each release unit must include the following fields:

| Field | Rule |
| --- | --- |
| `release_id` | `rel-YYYYMMDD-NNN` (UTC date + sequence) |
| `release_version` | semantic version (`MAJOR.MINOR.PATCH`) |
| `release_owner` | accountable operator/owner id |
| `scope_summary` | concise change scope and exclusions |
| `policy_impact` | `none` or explicit note (must remain `none` for phase_11 baseline docs-only updates) |
| `rollback_signal` | `hold_and_investigate`, `rollback_recommended`, or `rollback_required` |
| `evidence_refs` | readiness/support manifest paths and log locations |

## Versioning policy
- `MAJOR`: breaking operational contract, policy/auth boundary changes, or incompatible artifact format.
- `MINOR`: non-breaking operational capability expansion or new customer-facing governance artifacts.
- `PATCH`: docs/test/script fixes that preserve release-unit contracts.

## Release notes workflow
1. Copy `docs/release_notes_template.md` into the release work item.
2. Fill scope, verification, and artifact references.
3. Link current known issues from `docs/known_issues_register.md`.
4. Record rollback signal and rationale.
5. Append release evidence to `docs/staging_execution_record.md`.

## Known issues workflow
- Track each open issue in `docs/known_issues_register.md` with severity (`P0`-`P3`), owner, workaround, and target state.
- Move status only through `open` -> `mitigated` -> `resolved` (or `accepted_risk` with rationale).
- Any `P0` or repeated `P1` requires explicit go/no-go mention in release notes.

## Rollback signaling contract
- `hold_and_investigate`: no immediate rollback; increase monitoring and capture evidence.
- `rollback_recommended`: rollback within current release window unless owner documents explicit defer rationale.
- `rollback_required`: immediate rollback execution per:
  - `docs/rollback_checklist.md`
  - `docs/self_serve_update_rollback_safety.md`

When rollback is executed, include updated support-safe artifacts via:
- `scripts/self-serve-update-guard.ps1`
- `scripts/self-serve-support-intake.ps1`
- `scripts/self-serve-handoff-package.ps1`

## Minimum verification before release-governance signoff
- Targeted docs consistency and governance tests pass.
- Relevant lint checks pass for touched files.
- Staging execution record contains release-governance evidence for the update.
