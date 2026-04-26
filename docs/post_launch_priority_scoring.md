# Post-Launch Priority Scoring (Phase 13 / p13_t2)

## Purpose
Apply deterministic priority scoring to post-launch triage outputs for backlog and release governance decisions.

## Latest metadata
- generated_at_utc: 2026-04-26T02:25:43.4048404Z
- scoring_manifest: C:\Users\Ryosuke\AppData\Local\Temp\pytest-of-Ryosuke\pytest-559\test_phase15_hotfix_next_relea0\phase15-routing\post-launch-priority-score.manifest.json
- source_triage_manifest: C:\Users\Ryosuke\AppData\Local\Temp\pytest-of-Ryosuke\pytest-559\test_phase15_hotfix_next_relea0\phase15-routing\post-launch-triage.manifest.json
- scored_item_count: 1

## Tier counts
- High: 1
- Medium: 0
- Low: 0

## Formula
- (source_signal_count*2) + (source_bundle_count*2) + (impact_weight*3) + bucket_weight
