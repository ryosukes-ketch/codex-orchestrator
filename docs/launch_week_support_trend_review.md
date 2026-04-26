# Launch-Week Support Trend Review (Phase 12 / p12_t1)

## Purpose
Summarize launch-week support evidence for the last 7 days and produce bounded runbook delta candidates.

## Latest review metadata
- generated_at_utc: 2026-04-26T02:25:42.1598713Z
- analysis_window_utc: 2026-04-19T02:25:42.0843493Z -> 2026-04-26T02:25:42.0843493Z
- support_bundle_count: 1
- trend_manifest: C:\Users\Ryosuke\AppData\Local\Temp\pytest-of-Ryosuke\pytest-559\test_phase15_early_ops_inciden0\phase15-incident\launch-week-trend.manifest.json

## Top recurring categories (latest window)
- [runtime] occurrences=2, bundles=1
  - first triage: Run openclaw-gateway-check and operator-stage-report, then capture support bundle.
  - runbook delta candidate: Add a timeout budget table and endpoint-health first response sequence.
  - known issue trigger: Promote when runtime category appears in >=2 bundles within the review window.

## Aggregate counts
- runtime: 2
- provider_auth: 0
- policy: 0
- semantic_output: 0
- persistence_restore: 0
- operator_flow: 0
- unknown: 0

## Next actions
- 1) Apply top recurring category deltas to operator/commercial support runbooks.
- 2) Promote recurring categories to known issues when thresholds are met.
- 3) Re-run launch-week trend review after each support-cycle close to track trend movement.
