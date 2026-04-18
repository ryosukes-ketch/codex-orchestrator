# Macro Release Scanner v1.0

Macro Release Scanner is a production-oriented MVP for monitoring Kalshi macroeconomic release markets around official US data events.  
It ingests official schedules and actual values, discovers relevant Kalshi markets from deterministic mappings, captures market snapshots, detects repricing signals, scores them, sends Telegram alerts, stores data in PostgreSQL, and supports replay/backfill evaluation workflows.

## Product Overview

Supported release types in v1:
- FOMC rate decision
- CPI
- NFP (Employment Situation headline nonfarm payrolls)
- GDP advance estimate

Signal families:
- `PRE_RELEASE_PRESSURE`
- `RELEASE_SHOCK`
- `DELAYED_REPRICING`

This system is not a trading bot. It does not place orders or recommend trades.

## Architecture Summary

- `app/adapters`: external integrations (Kalshi, BLS, BEA, Fed, Telegram)
- `app/services`: ingestion, polling, parsing, signal detection, scoring, notification, replay/backfill/evaluation
- `app/services/monitoring_service.py`: operational anomaly detection, monitor event persistence, and critical monitor alerts
- `app/db`: SQLAlchemy async models/repositories and Alembic migrations
- `app/api`: minimal management and read endpoints
- `app/domain`: enums and typed models
- `config/market_mapping.yaml`: deterministic market mapping rules

## Continuation Governance Artifacts

- `docs/current_brief_template.json`
- `docs/current_work_order_template.json`

Continuation decisions use `GO`, `PAUSE`, `REVIEW`.

Additional governance/runbook references:
- `docs/codex_continuation_runbook.md`
- `docs/codex_automation_prompts.md`
- `docs/model_governance_policy.md`
- `docs/model_routing_policy.json`
- `docs/operator_workflow_runbook.md`
- `docs/staging_validation_plan.md`
- `docs/staging_execution_record.md`
- `docs/staging_evidence_template.md`
- `docs/staging_issue_triage_template.md`
- `docs/staging_signoff_template.md`
- `docs/live_validation_checklist.md`
- `docs/rollout_plan.md`
- `docs/rollback_checklist.md`
- `docs/production_readiness_gaps.md`
- `docs/system_requirements.md`
- `docs/mvp_requirements.md`
- `docs/pre_production_requirements.md`
- `docs/non_goals.md`
- `docs/requirement_traceability_matrix.md`
- `docs/acceptance_criteria.md`

Readiness/operator script references (contract compatibility):
- `scripts\refresh-openapi.ps1`
- `scripts\openclaw-gateway-check.ps1`
- `openclaw-evidence-capture.ps1`
- `operator-stage-report.ps1`
- `operator-audit-assert.ps1`
- `operator-full-cycle.ps1`
- `operator-cycle-suite.ps1`
- `operator-handoff-envelope.ps1`
- `operator-stage-gate.ps1`
- `operator-menu.ps1`
- `operator-status.ps1 -BundleManifestPath`
- `operator-stage-report.ps1 -BundleManifestPath`
- `operator-audit-assert.ps1 -BundleManifestPath`
- `Readiness Replay Summary`
- `legacy_fallback_normalizations`
- `status-summary.json`
- `bundle-manifest.json`
- `readiness-manifest-`
- `readiness-summary-`

Common readiness/operator flags:
- `-AuditJsonPath`
- `-NoEventDerivedTelemetry`
- `-SummaryOutPath`
- `-BundleManifestPath`
- `-RunOpenClawGatewayCheck`
- `-OperatorMaxLlmTransportFallbacks`
- `-OperatorRequireAuthEvidence`
- `-OperatorAuthorizationOperator`
- `-OperatorExpectedAuthRoles`
- `-OperatorAuthPolicyMode`
- `-OperatorBreakglass`
- `-OperatorBreakglassReason`
- `-OperatorBreakglassActor`

## Setup

1. Create Python 3.12 environment.
2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Copy env file and fill values:

```bash
cp .env.example .env
```

4. Ensure PostgreSQL is running and `DATABASE_URL` is valid.
   - `monitor --once` and `live --once` require reachable PostgreSQL.

## Environment Variables

Required/primary:
- `APP_ENV`
- `LOG_LEVEL`
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `API_WRITE_TOKEN`
- `KALSHI_BASE_URL`
- `BLS_BASE_URL`
- `BEA_BASE_URL`
- `FED_BASE_URL`
- `DISPLAY_TIMEZONE` (default `Asia/Tokyo`)
- `POLL_INTERVAL_SECONDS`
- `ACTIVE_RELEASE_WINDOW_MINUTES`

Retry/network:
- `REQUEST_TIMEOUT_SECONDS`
- `MAX_RETRIES`
- `BACKOFF_BASE_SECONDS`

Monitoring:
- `MONITORING_ENABLED`
- `MONITORING_INTERVAL_SECONDS`
- `MONITORING_TELEGRAM_CHAT_ID` (optional; falls back to `TELEGRAM_CHAT_ID`)
- `MONITORING_ALERT_COOLDOWN_CRITICAL_SECONDS`
- `MONITORING_ACTUAL_MISSING_GRACE_SECONDS`
- `MONITORING_NO_SIGNAL_GRACE_SECONDS`
- `MONITORING_SIGNAL_BURST_THRESHOLD`
- `MONITORING_SIGNAL_BURST_MARKET_THRESHOLD`
- `MONITORING_NOTIFICATION_FAILURE_BURST_THRESHOLD`

Operator/local profile:
- `STATE_BACKEND`
- `STATE_BACKEND_STRICT`
- `SQLITE_DB_PATH`
- `OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS`
- `OPERATOR_API_TIMEOUT_SECONDS`

## Database Migration

```bash
alembic upgrade head
```

Or:

```bash
./scripts/init_db.sh
```

## Run Modes

Live:

```bash
python -m app.main live
```

Live once without remote schedule ingestion (local/dev fallback):

```bash
python -m app.main live --once --skip-remote-schedules
```

Backfill:

```bash
python -m app.main backfill --from 2026-01-01T00:00:00Z --to 2026-03-01T00:00:00Z
```

Replay:

```bash
python -m app.main replay --release-id CPI-2026-04-10
```

API:

```bash
python -m app.main api
```

Monitoring (single tick):

```bash
python -m app.main monitor --once
```

Monitoring (loop):

```bash
python -m app.main monitor --loop
```

`monitor --once` is for deterministic local checks and CI smoke, while `monitor --loop` is for long-running watch mode.

Manual release seeding (YAML):

```bash
python -m app.main seed-releases --file config/manual_releases.yaml
```

Manual actual seeding (YAML):

```bash
python -m app.main seed-actuals --file config/manual_actuals.yaml
```

Manual market seeding (YAML):

```bash
python -m app.main seed-markets --file config/manual_markets.yaml
```

Manual snapshot seeding (YAML):

```bash
python -m app.main seed-snapshots --file config/manual_snapshots.yaml
```

Local BLS-free smoke (single command):

```powershell
.\scripts\local-dev-smoke.ps1
```

Optional read-only API surface check (requires running API server):

```powershell
python -m app.main api
.\scripts\local-dev-smoke.ps1 -CheckReadOnlyApi -ApiBaseUrl http://127.0.0.1:8000
```

This runs:
1. `seed-releases`
2. `seed-actuals`
3. `seed-markets`
4. `seed-snapshots`
5. `live --once --skip-remote-schedules`
6. `monitor --once`

Seed file format (`config/manual_releases.yaml`):

```yaml
releases:
  - release_type: CPI
    release_name: Consumer Price Index
    scheduled_time_utc: "2026-06-11T12:30:00Z"
    source_url: "manual://cpi-2026-06-11"
    status: scheduled
```

Actual seed file format (`config/manual_actuals.yaml`):

```yaml
actuals:
  - release_type: CPI
    release_name: Consumer Price Index
    scheduled_time_utc: "2026-06-11T12:30:00Z"
    actual_value_num: 3.3
    actual_value_text: "Headline CPI YoY 3.3%"
    source_url: "manual://actual/cpi-dev-seed"
    released_at_utc: "2026-06-11T12:30:00Z"
    status: released
```

Market seed file format (`config/manual_markets.yaml`):

```yaml
markets:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    platform: kalshi
    title: "Will CPI Dev Seed Near Term print above 3.1%?"
    close_time_utc: "2026-04-19T13:00:00Z"
    status: active
    release_type: CPI
    release_name: CPI Dev Seed Near Term
    scheduled_time_utc: "2026-04-19T12:30:00Z"
    mapping_confidence: 1.0
    mapping_payload_json:
      manual_seed: true
      threshold:
        comparator: above
        value: 3.1
        unit: "%"
```

Snapshot seed file format (`config/manual_snapshots.yaml`):

```yaml
snapshots:
  - market_ticker: CPI-DEV-APR19-ABOVE-3.1
    captured_at_utc: "2026-04-19T12:20:00Z"
    yes_bid: 0.44
    yes_ask: 0.48
    volume: 130
```

Operational note:
- If runtime dependencies are unavailable (for example DB down or upstream HTTP errors), commands fail once with a clear error log and attempt graceful async cleanup.
- Manual release seeding and `--skip-remote-schedules` are intended for local development/internal validation when upstream schedule pages are temporarily unavailable.
- Manual actual seeding is intended for local development/internal validation when upstream actual-value ingestion is unavailable.
- Manual market seeding is intended for local development/internal validation when upstream discovery/mapping is insufficient.
- Manual snapshot seeding is intended for local development/internal validation when upstream polling data is unavailable or insufficient.
- For local/internal compatibility, manual market mappings can include `release_id`, `threshold`, and `contract_interpretation` in `mapping_payload_json`; non-manual production mapping behavior is unchanged.
- Manual markets with `mapping_payload_json.manual_seed=true` are treated as synthetic in local dev mode: upstream Kalshi detail/orderbook polling is skipped and seeded local snapshots are used as the source of truth.

## SQLite operational policy (local ops)

- Local readiness profile uses `STATE_BACKEND=sqlite` and `STATE_BACKEND_STRICT=true`.
- SQLite local operation is intentionally persistence-focused and is **not treated as a production-grade** concurrency validation profile.
- Keep `OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS` and `OPERATOR_API_TIMEOUT_SECONDS` explicitly configured for stable local operator runs.

## API Endpoints

- `GET /health`
- `GET /status`
- `GET /monitor`
- `GET /signals`
- `GET /releases/upcoming`
- `GET /signals/recent`
- `GET /monitoring/status`
- `GET /monitoring/events/recent`
- `GET /monitoring/events/open`
- `POST /jobs/backfill` (requires `Authorization: Bearer <API_WRITE_TOKEN>`)
- `POST /jobs/replay` (requires `Authorization: Bearer <API_WRITE_TOKEN>`)

## MVP Completion Criteria

### 1. Local MVP Pass

The local MVP gate is satisfied when all of the following pass:
- release seeding succeeds (`seed-releases`)
- actual seeding succeeds (`seed-actuals`)
- market seeding succeeds (`seed-markets`)
- snapshot seeding succeeds (`seed-snapshots`)
- `live --once --skip-remote-schedules` succeeds
- at least one signal is persisted in `signals`
- `monitor --once` reflects expected open/resolved transitions for active scenarios
- Telegram signal notifications succeed for high/critical signals
- readiness/docs/env contract tests pass

Manual seed roles in local BLS-free mode:
- releases: scheduled events to monitor
- actuals: official-value stand-in for actual-dependent logic
- markets: explicit release-linked market catalog rows
- snapshots: time-series price points required by signal windows

### 2. Internal Beta Pass

Internal beta readiness expects:
- repeatable runs via `.\scripts\local-dev-smoke.ps1`
- deterministic smoke summary visibility (counts, latest signals, open/resolved monitor events)
- documented operator workflow and readiness runbook coverage
- Telegram notification paths validated in an internal non-production chat

### 3. Production Readiness Remaining Gaps

Remaining gaps before production rollout include:
- full real-upstream schedule/actual resiliency validation (beyond local BLS-free mode)
- production secret handling and token rotation execution plan
- production database/availability validation beyond local SQLite/Postgres dev profiles
- deployment/monitoring SLO hardening and incident runbook finalization

## Telegram Operations

- Pulse is the MacroPulse Telegram notification interface for signal and monitoring events.
- Signal notifications and monitoring alerts share the existing notifier path, but monitoring can target `MONITORING_TELEGRAM_CHAT_ID` (falls back to `TELEGRAM_CHAT_ID`).
- In local runs, use `monitor --once` to validate alert/event transitions after each deterministic cycle.
- For watch mode, use `monitor --loop` and keep critical cooldown behavior enabled.
- Read-only observability surfaces are available via API endpoints: `/status`, `/monitor`, `/signals`.
- Internal beta quick path: run `.\scripts\local-dev-smoke.ps1`, then verify `/status`, `/monitor`, and `/signals`.
- Before broader deployment, rotate bot token/chat settings, separate dev/prod tokens, and validate send path with a non-production chat target.

## Testing

Run targeted MVP tests:

```bash
pytest tests/test_threshold_parser.py tests/test_market_mapping.py tests/test_signal_engine.py tests/test_scoring_engine.py tests/test_cooldown.py tests/test_evaluation.py tests/test_api_routes.py tests/test_replay_flow.py
```

## Assumptions

- Schedule ingestion uses deterministic HTML date extraction from official pages; official source page formats may evolve.
- Stored `source_url` values are release-content URLs (or deterministic URL templates), not schedule pages.
- For FOMC v1, statement time is fixed to 14:00 ET on the meeting decision date.
- `release_id` is deterministic (`<release_type>-<date>`).
- Kalshi public endpoint shapes can vary; adapter parsing handles common payload variants and degrades gracefully when fields are missing.
- In live mode, if official actual parsing fails, the error context is persisted in `release_actuals.parsed_payload_json`, and `DELAYED_REPRICING` will not trigger.
- Write job routes are denied when `API_WRITE_TOKEN` is unset.

## Known Limitations

- Official data parser regexes are deterministic but can be fragile to major upstream HTML/text template changes.
- Some release-content URL templates (especially GDP advance slug shapes) are deterministic heuristics and may require updates if publisher URL conventions change.
- No dashboard UI is included in v1.
- API endpoints are intentionally minimal and synchronous for management operations.
- Replay/backfill rely on already persisted snapshot history.
- In-app monitoring complements, but does not replace, external infrastructure monitoring/alerting.
- Fallback monitoring tick-failure alerts use in-memory cooldown state so they remain available when DB access itself is unavailable.
- Monitoring checks for missing actuals intentionally focus on a recent due window (last 30 days) to avoid stale historical gaps dominating current health status.
- Warning-level monitor events are persisted and queryable but are not auto-alerted to Telegram in v1.
- Official sources (including BLS) still depend on upstream site availability and normal outbound HTTPS access from the runtime environment.
- All three external HTTP adapters (BLS, Fed, BEA) use browser-like headers and `follow_redirects=True` to reduce 403 responses from upstream sites.
- `request_with_backoff` does not retry 4xx responses (client errors such as 403/404 are deterministic and retrying them would only add delay). 5xx server errors are still retried with exponential backoff.
