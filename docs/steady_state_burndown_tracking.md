# Steady-State Burndown Tracking

## Purpose
Track open steady-state improvement backlog items over time and emit a deterministic burn-down decision package.

## Command

```powershell
.\scripts\ga-steady-state-burndown.ps1 -Zip
```

Optional explicit inputs:

```powershell
.\scripts\ga-steady-state-burndown.ps1 `
  -ImprovementBacklogManifestPath .\logs\ga-steady-state\improvement-backlog-<timestamp>\ga-steady-state-improvement-backlog.manifest.json `
  -PreviousBurndownManifestPath .\logs\ga-steady-state\burndown-<timestamp>\ga-steady-state-burndown.manifest.json `
  -MaxOpenPreview 10 `
  -Zip
```

## Output contract

- `bundle_type`: `steady_state_burndown_tracking`
- summary fields:
  - `open_item_count`
  - `closed_item_count`
  - `previous_open_item_count`
  - `delta_open_item_count`
  - `closed_since_previous_count`
  - `burndown_decision`
  - `burndown_decision_reasons`
- details fields:
  - `open_items_preview`
  - `next_steps`

## Decision vocabulary

- `go`: no open items remain.
- `watch`: open items remain but trend is still bounded.
- `escalate`: open backlog is not trending down versus previous burndown snapshot.

## Operational use

Use this package as the steady-state closure tracking checkpoint:
1. run after generating `steady_state_improvement_backlog`.
2. confirm open-item trend is decreasing.
3. route `escalate` decisions to release-ops watch and closure ownership.
