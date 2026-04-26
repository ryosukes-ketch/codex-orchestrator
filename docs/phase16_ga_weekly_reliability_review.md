# Phase 16 GA Weekly Reliability Review

## Purpose
Run a deterministic weekly GA adoption reliability review using existing support evidence, recurring hardening manifests, and explicit recommendation output.

## Command

```powershell
.\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip
```

Optional explicit inputs:

```powershell
.\scripts\ga-weekly-reliability-review.ps1 `
  -TrendManifestPath logs\post-launch-ops\launch-week-trend-<ts>\launch-week-trend.manifest.json `
  -HardeningManifestPath logs\post-launch-ops\recurring-issue-hardening-<ts>\recurring-issue-hardening.manifest.json `
  -OutPath logs\ga-adoption\weekly-review-<ts>\ga-weekly-reliability-review.manifest.json `
  -SummaryOutPath logs\ga-adoption\weekly-review-<ts>\ga-weekly-reliability-review.summary.json
```

## Output contract

- `bundle_type`: `phase16_ga_weekly_reliability_review`
- `summary`:
  - `support_bundle_count`
  - `top_recurring_category_count`
  - `hardening_action_count`
  - `p1_hardening_action_count`
  - `schema_issue_count`
  - `recommendation`
- `source`:
  - `trend_manifest_path`
  - `hardening_manifest_path`
- `details`:
  - `top_recurring_categories`
  - `hardening_actions`
  - `schema_issues`

## Recommendation vocabulary

- `urgent_hardening_cycle`
  - one or more `P1` hardening actions or schema issues detected.
- `targeted_hardening_cycle`
  - recurring categories exist without `P1`/schema blockers.
- `monitor_only_cycle`
  - no recurring category spike and no schema hardening blockers.

## Phase 16 evidence closure guidance

For each weekly cycle, retain:

- `ga-weekly-reliability-review.manifest.json`
- `ga-weekly-reliability-review.summary.json`
- source trend + recurring hardening manifests
- one staging record entry in `docs/staging_execution_record.md`
