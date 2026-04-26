# Phase 18 Quarterly Governance and Scale Planning

## Purpose
Convert phase_17 monthly reliability and closure-SLA routing outputs into a deterministic quarterly governance package with explicit owner commitment status and review decision evidence.

## Commands

```powershell
.\scripts\ga-quarterly-reliability-governance.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-closure-sla-ownership.ps1 -WindowDays 90 -Zip
.\scripts\ga-quarterly-review-package.ps1 -Zip
```

## Output contracts

### 1) Quarterly reliability governance

- script: `scripts/ga-quarterly-reliability-governance.ps1`
- `bundle_type`: `phase18_quarterly_reliability_governance`
- core summary fields:
  - `monthly_package_count`
  - `monthly_decision_counts`
  - `recommendation_totals`
  - `closure_sla_overdue_action_count_total`
  - `closure_sla_overdue_p1_count_total`
  - `reliability_health_score_average`
  - `quarterly_decision`

### 2) Quarterly closure-SLA ownership

- script: `scripts/ga-quarterly-closure-sla-ownership.ps1`
- `bundle_type`: `phase18_quarterly_closure_sla_ownership`
- core summary fields:
  - `routing_manifest_count`
  - `owner_commitment_count`
  - `route_totals`
  - `carry_over_action_count`
  - `quarterly_closure_decision`
- core details fields:
  - `owner_commitments` (owner, open/overdue counts, commitment_status)
  - `carry_over_actions`

### 3) Quarterly review package

- script: `scripts/ga-quarterly-review-package.ps1`
- `bundle_type`: `phase18_quarterly_review_package`
- core summary fields:
  - `reliability_quarterly_decision`
  - `closure_quarterly_decision`
  - `quarterly_review_decision`
  - `reliability_health_score_average`
  - `owner_at_risk_count`
  - `carry_over_action_count`

## Decision vocabulary

- `go`
  - quarterly reliability and closure ownership both remain stable.
- `watch`
  - no immediate escalation signal, but at-risk owner pressure or carry-over exists.
- `escalate`
  - escalation pressure exists in reliability or closure ownership package.

## Phase 18 evidence closure guidance

Retain:

- `ga-quarterly-reliability-governance.manifest.json`
- `ga-quarterly-closure-sla-ownership.manifest.json`
- `ga-quarterly-review-package.manifest.json`
- one phase_18 evidence entry in `docs/staging_execution_record.md`
