# Steady-State Improvement Backlog

## Purpose
Convert phase_20/phase_21/phase_22 closeout outcomes into a bounded operational improvement backlog for steady-state maintenance cycles.

## Command

```powershell
.\scripts\ga-steady-state-improvement-backlog.ps1 -Zip
```

Optional explicit sources:

```powershell
.\scripts\ga-steady-state-improvement-backlog.ps1 `
  -Phase20CloseoutManifestPath .\logs\ga-ops\...\phase20-environment-support-closeout.manifest.json `
  -Phase21CloseoutManifestPath .\logs\ga-compliance\...\phase21-auditability-closeout.manifest.json `
  -Phase22CloseoutManifestPath .\logs\ga-steady-state\...\phase22-steady-state-closeout.manifest.json `
  -MaxBacklogItems 20 `
  -Zip
```

## Output contract

- `bundle_type`: `steady_state_improvement_backlog`
- summary fields:
  - `backlog_item_count`
  - `high_priority_count`
  - `medium_priority_count`
  - `missing_source_count`
  - `steady_state_improvement_decision`
- details fields:
  - `backlog_items`
  - `missing_sources`

## Decision vocabulary

- `go`: no watch/escalate closeout outcomes detected.
- `watch`: one or more source closeouts are `watch`/`escalate` or required sources are missing.

## Operational use

Use this package in weekly steady-state review:
1. promote high priority items to immediate mitigation.
2. route medium priority items to the next bounded reliability cycle.
3. re-run after closeout updates to verify backlog trend reduction.

