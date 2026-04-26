# Steady-State Escalation Watchlist Ownership Routing

## Purpose
Route `watch` / `escalate` checkpoint items into deterministic owner/status/ETA/SLA watchlist records for steady-state closure tracking.

## Command

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 -Zip
```

Optional explicit inputs:

```powershell
.\scripts\ga-steady-state-escalation-watchlist-route.ps1 `
  -CheckpointManifestPath .\logs\ga-steady-state\checkpoint-refresh-<timestamp>\ga-steady-state-checkpoint-refresh.manifest.json `
  -PreviousRoutingManifestPath .\logs\ga-steady-state\watchlist-route-<timestamp>\ga-steady-state-escalation-watchlist-route.manifest.json `
  -OwnerAckPath .\docs\steady_state_watchlist_owner_ack.json `
  -WatchSlaDays 7 `
  -EscalateSlaDays 3 `
  -Zip
```

## Output contract

- `bundle_type`: `steady_state_escalation_watchlist_routing`
- summary fields:
  - `watchlist_item_count`
  - `previous_watchlist_item_count`
  - `delta_watchlist_item_count`
  - `owner_ack_rules_path`
  - `owner_ack_rules_count`
  - `owner_ack_applied_count`
  - `owner_count`
  - `decision_counts`
  - `overall_watchlist_decision`
  - `overall_watchlist_decision_reasons`
- details fields:
  - `owner_routing`
  - `watchlist_items`
  - `next_steps`

## Watchlist item required fields

Every watchlist item includes:
- `owner`
- `status`
- `eta_utc`
- `next_review_utc`
- `sla_days`
- `escalation_reason`

## Decision vocabulary

- `go`: no watch/escalate items remain.
- `watch`: watch items remain with bounded ownership tracking.
- `escalate`: escalate items remain and require immediate ownership action.

## Operational use

Use this package as the steady-state final closeout input:
1. run after checkpoint refresh.
2. confirm owner assignment and ETA for all open watchlist items.
3. ensure `delta_watchlist_item_count` trends downward across cycles.
4. when `status=owner_assignment_required` persists for one full cadence cycle, register/update the issue in `docs/known_issues_register.md` and route the item through release-ops go/hold/rollback meeting notes.

## Owner acknowledgment rules

Use `docs/steady_state_watchlist_owner_ack.json` to acknowledge stable watchlist items without weakening decision semantics.

- Matching fields (all optional filters):
  - `checkpoint_lane`
  - `decision`
  - `source_bundle_type`
  - `source_manifest_path`
- Override fields:
  - `owner`
  - `status`
  - `sla_days`
  - `next_review_utc`

Acknowledged items keep their `decision` (`watch`/`escalate`) but can move from
`owner_assignment_required` to `tracking`/`in_progress` so runtime pause
thresholds reflect unresolved owner assignment only.
