# Release/Ops Cadence Baseline

## Purpose
Provide a deterministic cadence contract that links reliability operations, support governance, and release-train decisioning.

## Cadence table

| Cadence | Owner | Primary command | Output bundle |
|---|---|---|---|
| Weekly | operations | `.\scripts\ga-weekly-reliability-review.ps1 -WindowDays 7 -Zip` | `phase16_ga_weekly_reliability_review` |
| Monthly | customer_success | `.\scripts\ga-monthly-reliability-targets.ps1 -WindowDays 30 -Zip` | `phase17_ga_monthly_reliability_target_package` |
| Quarterly | governance | `.\scripts\ga-quarterly-review-package.ps1 -Zip` | `phase18_quarterly_review_package` |
| Release | release_manager | `.\scripts\release-train-evidence-export.ps1 -Zip` | `phase14_release_train_evidence_export` |

## Cadence checks

- Weekly output is consumed by monthly target aggregation.
- Monthly + closure ownership outputs are consumed by quarterly review package.
- Quarterly review influences upgrade/migration and release governance decisions.
- Release-train evidence must remain traceable through compliance-lite ledger outputs.

