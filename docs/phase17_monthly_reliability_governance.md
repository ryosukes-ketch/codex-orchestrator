# Phase 17 Monthly Reliability Governance

## Purpose
Aggregate weekly GA reliability review evidence into a deterministic monthly governance package with KPI summary, closure SLA aging, and decision output.

## Command

```powershell
.\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip
```

Optional explicit inputs:

```powershell
.\scripts\ga-monthly-reliability-targets.ps1 `
  -WeeklyManifestPaths logs\ga-adoption\weekly-review-<ts1>\ga-weekly-reliability-review.manifest.json,logs\ga-adoption\weekly-review-<ts2>\ga-weekly-reliability-review.manifest.json `
  -RoutingManifestPaths logs\ga-launch\phase15-closeout-<ts>\hotfix-next-release-route.manifest.json `
  -KnownIssuesPath docs\known_issues_register.md `
  -OutPath logs\ga-adoption\monthly-targets-<ts>\ga-monthly-reliability-targets.manifest.json `
  -SummaryOutPath logs\ga-adoption\monthly-targets-<ts>\ga-monthly-reliability-targets.summary.json
```

## Output contract

- `bundle_type`: `phase17_ga_monthly_reliability_target_package`
- `summary`:
  - `weekly_review_count`
  - `support_bundle_count_total`
  - `top_recurring_category_count_total`
  - `hardening_action_count_total`
  - `recommendation_counts`
  - `routing_summary`
  - `known_issue_snapshot`
  - `known_issue_delta`
  - `closure_sla`
  - `reliability_health_score`
  - `monthly_decision`
  - `monthly_decision_reasons`
- `details`:
  - `top_recurring_categories`
  - `closure_sla_open_actions`
  - `decision_next_steps`

## Monthly decision vocabulary

- `go`
  - no urgent weekly recommendation and no overdue P1 closure-SLA action.
- `watch`
  - no immediate escalation trigger, but overdue closure-SLA action or repeated targeted hardening pressure exists.
- `escalate`
  - urgent weekly hardening recommendation or overdue P1 closure-SLA action exists.

## Closure SLA interpretation

Thresholds are fixed per priority:

- `P1`: 7 days
- `P2`: 14 days
- `P3`: 30 days

The summary includes:

- `open_action_count`
- `overdue_action_count`
- `overdue_p1_count`
- `unresolved_aging_buckets` (`le_7_days`, `d8_14_days`, `d15_30_days`, `gt_30_days`)

## Phase 17 evidence closure guidance

For each monthly cycle, retain:

- `ga-monthly-reliability-targets.manifest.json`
- `ga-monthly-reliability-targets.summary.json`
- source weekly reliability manifests
- source hotfix/next-release routing manifests (if present)
- one staging record entry in `docs/staging_execution_record.md`

## Follow-up routing loop (`p17_t2`)

After generating the monthly target package, run:

```powershell
.\scripts\ga-closure-sla-breach-route.ps1 -Zip
```

Then update owner status and runbook deltas from:

- `phase17_closure_sla_breach_routing` manifest
- `owner_open_counts`
- `closure_sla_routed_actions`
