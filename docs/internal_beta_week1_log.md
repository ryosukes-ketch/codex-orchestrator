# MacroPulse Internal Beta Week 1 Log

## Template

## Entry
- Date:
- Session type: per-session / daily / pre-demo
- Operator:
- Environment:
- API base URL:

## 1. Smoke result
- local-dev-smoke result: PASS / REVIEW / STOP

## 2. `/status` summary
- monitoring_status:
- signals_count:
- open_monitor_events_count:
- resolved_monitor_events_count:
- latest_live_cycle_success_at_utc:
- release_calendar_count:
- release_actuals_count:
- market_catalog_count:
- market_snapshots_count:

## 3. `/monitor` summary
- open monitor events count:
- top open monitor types:
- severity summary:

## 4. `/signals` summary
- signals returned:
- top signal types:
- highest severity:
- notable markets:

## 5. Operational judgment
- Session judgment: PASS / REVIEW / STOP
- Reason:
- Immediate action required: yes / no

## 6. Notes
- upstream anomalies:
- manual intervention:
- runbook/doc improvement notes:
- next check timing:

---

## Week 1 - Entry 1

## Entry
- Date: 2026-04-19 (JST)
- Session type: per-session
- Operator: internal-beta-operator
- Environment: local internal beta
- API base URL: http://127.0.0.1:18000

## 1. Smoke result
- local-dev-smoke result: PASS

## 2. `/status` summary
- monitoring_status: ok
- signals_count: 2
- open_monitor_events_count: 0
- resolved_monitor_events_count: 3
- latest_live_cycle_success_at_utc: 2026-04-19T04:05:20.459408Z
- release_calendar_count: 6
- release_actuals_count: 3
- market_catalog_count: 18610
- market_snapshots_count: 11

## 3. `/monitor` summary
- open monitor events count: 0
- top open monitor types: none
- severity summary: none open

## 4. `/signals` summary
- signals returned: 2
- top signal types: RELEASE_SHOCK, PRE_RELEASE_PRESSURE
- highest severity: critical
- notable markets: CPI-DEV-APR18-ABOVE-3.1

## 5. Operational judgment
- Session judgment: PASS
- Reason: smoke/status/monitor/signals checks all healthy in the same run
- Immediate action required: no

## 6. Notes
- upstream anomalies: none
- manual intervention: none
- runbook/doc improvement notes: none
- next check timing: next per-session run
