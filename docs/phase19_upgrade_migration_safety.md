# Phase 19 Upgrade and Migration Safety Operations

## Purpose
Standardize upgrade and migration safety operations for customer-managed environments by packaging deterministic impact analysis, migration rehearsal, rollback safety, and closeout evidence.

## Commands

```powershell
.\scripts\ga-upgrade-impact-matrix.ps1 -Zip
.\scripts\ga-migration-rehearsal-package.ps1 -Zip
.\scripts\ga-upgrade-rollback-safety.ps1 -Zip
.\scripts\ga-upgrade-evidence-closeout.ps1 -Zip
```

## Output contracts

### 1) Upgrade impact matrix

- script: `scripts/ga-upgrade-impact-matrix.ps1`
- `bundle_type`: `phase19_upgrade_impact_matrix`
- core summary fields:
  - `quarterly_review_decision`
  - `owner_at_risk_count`
  - `carry_over_action_count`
  - `known_issue_status_counts`
  - `impact_lane_counts`
  - `upgrade_impact_decision`

### 2) Migration rehearsal package

- script: `scripts/ga-migration-rehearsal-package.ps1`
- `bundle_type`: `phase19_migration_rehearsal_package`
- core summary fields:
  - `readiness_decision`
  - `upgrade_impact_decision`
  - `rehearsal_ready`
  - `missing_required_script_count`
  - `rehearsal_decision`
- core details fields:
  - `rehearsal_steps`
  - `missing_required_scripts`

### 3) Upgrade rollback safety package

- script: `scripts/ga-upgrade-rollback-safety.ps1`
- `bundle_type`: `phase19_upgrade_rollback_safety`
- core summary fields:
  - `upgrade_impact_decision`
  - `rehearsal_ready`
  - `required_control_count`
  - `rollback_safety_decision`
- core details fields:
  - `rollback_controls`

### 4) Upgrade evidence closeout

- script: `scripts/ga-upgrade-evidence-closeout.ps1`
- `bundle_type`: `phase19_upgrade_evidence_closeout`
- core summary fields:
  - `impact_decision`
  - `rehearsal_decision`
  - `rollback_decision`
  - `closeout_decision`
- source manifest fields:
  - `impact_manifest_path`
  - `rehearsal_manifest_path`
  - `rollback_manifest_path`

## Decision vocabulary

- `go`
  - upgrade/migration safety prerequisites are satisfied.
- `watch`
  - one or more prerequisites require remediation before promotion.

## Phase 19 evidence closure guidance

Retain:

- `ga-upgrade-impact-matrix.manifest.json`
- `ga-migration-rehearsal-package.manifest.json`
- `ga-upgrade-rollback-safety.manifest.json`
- `phase19-upgrade-evidence-closeout.manifest.json`
- one phase_19 evidence entry in `docs/staging_execution_record.md`
