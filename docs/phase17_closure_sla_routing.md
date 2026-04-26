# Phase 17 Closure-SLA Breach Routing

## Purpose
Route monthly closure-SLA open actions into deterministic owner/status lanes and publish a runbook-delta ownership loop for steady-state customer-success operations.

## Command

```powershell
.\scripts\ga-closure-sla-breach-route.ps1 -Zip
```

Optional explicit monthly input:

```powershell
.\scripts\ga-closure-sla-breach-route.ps1 `
  -MonthlyManifestPath logs\ga-adoption\monthly-targets-<ts>\ga-monthly-reliability-targets.manifest.json `
  -OutPath logs\ga-adoption\closure-sla-routing-<ts>\ga-closure-sla-routing.manifest.json `
  -SummaryOutPath logs\ga-adoption\closure-sla-routing-<ts>\ga-closure-sla-routing.summary.json
```

## Output contract

- `bundle_type`: `phase17_closure_sla_breach_routing`
- `summary`:
  - `open_action_count`
  - `route_counts` (`immediate_escalation`, `targeted_hardening`, `watchlist`, `monitor`)
  - `owner_open_counts` (explicit `owner`, `open_action_count`, `overdue_action_count`)
  - `closure_sla_decision`
  - `closure_sla_decision_reasons`
- `details`:
  - `closure_sla_routed_actions` (owner/status/category/priority/route/sla/overdue)
  - `runbook_delta_ownership_loop`
  - `next_steps`

## Routing vocabulary

- `immediate_escalation`
  - overdue `P1` actions.
- `targeted_hardening`
  - overdue non-`P1` actions.
- `watchlist`
  - not overdue yet, but approaching SLA threshold.
- `monitor`
  - no immediate risk signal.

## Closure-SLA ownership loop

For each monthly cycle:

1. Assign every `immediate_escalation` action to the published owner with explicit ETA.
2. Convert `targeted_hardening` actions into bounded runbook deltas.
3. Re-run routing after owner status updates and track drift in `owner_open_counts`.

## Phase 17 evidence closure guidance

Retain:

- `ga-monthly-reliability-targets.manifest.json`
- `ga-closure-sla-routing.manifest.json`
- `ga-closure-sla-routing.summary.json`
- one phase_17 closeout entry in `docs/staging_execution_record.md`
