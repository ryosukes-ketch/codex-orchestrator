# Steady-State Checkpoint Refresh

## Purpose
Refresh monthly, quarterly, and release checkpoint evidence into one deterministic steady-state checkpoint package.

## Command

```powershell
.\scripts\ga-steady-state-checkpoint-refresh.ps1 -Zip
```

Optional explicit inputs:

```powershell
.\scripts\ga-steady-state-checkpoint-refresh.ps1 `
  -MonthlyCheckpointManifestPath .\logs\ga-adoption\monthly-targets-<timestamp>\ga-monthly-reliability-targets.manifest.json `
  -QuarterlyCheckpointManifestPath .\logs\ga-adoption\quarterly-review-package-<timestamp>\ga-quarterly-review-package.manifest.json `
  -ReleaseCheckpointManifestPath .\logs\release-train\evidence-<timestamp>\release-train-evidence.manifest.json `
  -PreviousCheckpointManifestPath .\logs\ga-steady-state\checkpoint-refresh-<timestamp>\ga-steady-state-checkpoint-refresh.manifest.json `
  -Zip
```

## Output contract

- `bundle_type`: `steady_state_checkpoint_refresh`
- summary fields:
  - `monthly_checkpoint_decision`
  - `quarterly_checkpoint_decision`
  - `release_checkpoint_decision`
  - `overall_checkpoint_decision`
  - `overall_checkpoint_decision_reasons`
  - `overall_checkpoint_decision_delta`
  - `missing_checkpoint_count`
  - `checkpoint_decision_counts`
- details fields:
  - `checkpoints`
  - `missing_checkpoints`
  - `next_steps`

## Decision vocabulary

- `go`: all checkpoint lanes in go posture.
- `watch`: any lane in watch posture or a source lane is missing.
- `escalate`: any lane in escalate posture.

## Operational use

Use this package in steady-state cadence checkpoints:
1. run after monthly/quarterly/release evidence updates.
2. verify `overall_checkpoint_decision` and `overall_checkpoint_decision_delta`.
3. route `escalate` to immediate release-ops ownership and closure tracking.
4. run `.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -Zip` to assign owner/status/ETA/SLA records for watch/escalate lanes.

Reference:
- `docs/steady_state_watchlist_ownership_routing.md`
