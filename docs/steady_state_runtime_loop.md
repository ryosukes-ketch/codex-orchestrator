# Steady-State Runtime Loop

## Purpose
Provide a single-entry operational loop after roadmap completion (`steady_state` mode) without creating new phases.

## Single entrypoint

```powershell
.\scripts\steady-state-run.ps1 -Mode daily -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

Weekly heavier loop:

```powershell
.\scripts\steady-state-run.ps1 -Mode weekly -WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json -Zip
```

## Guardrails
- No new phase creation (`phase_23` and beyond are disabled in steady-state operations).
- No `ss_t5` task creation.
- No strict auth/policy relaxation.
- No architecture expansion in the runtime loop.
- External provider/runtime failures are classified and paused instead of patched in-loop.

## Loop responsibilities
1. Preflight and lock validation.
2. Cadence execution (`weekly` mode).
3. Checkpoint refresh.
4. Watchlist routing.
5. Improvement backlog + burndown refresh (`weekly` mode).
6. Known issue update decision.
7. Staging execution record append.
8. Runtime state file update.
9. Pause classification on repeated external/operational blockers.

## Output contract
Per run, the script writes:
- `logs\ga-steady-state\runs\<timestamp>\steady-state-run.manifest.json`
- `logs\ga-steady-state\runs\<timestamp>\steady-state-run.summary.json`
- `logs\ga-steady-state\runs\<timestamp>\staging_append_preview.md`
- `logs\ga-steady-state\runs\<timestamp>\*.log` (step logs)
- `logs\ga-steady-state\runs\<timestamp>.zip` (if `-Zip`)

## Runtime state
State file:
- `docs\steady_state_runtime_state.json`

Required tracked fields:
- `last_run_at`
- `last_status`
- `last_cycle_id`
- `last_checkpoint_manifest`
- `last_watchlist_manifest`
- `last_known_issue_update`
- `consecutive_escalate_count`
- `open_watch_count`
- `open_escalate_count`
- `last_owner_assignment_pending_count`
- `paused_reason`

## Pause conditions
The loop marks `paused=true` when one of the following is detected:
- repeated external blocker pattern (provider/OpenClaw/runtime failure signatures),
- owner-assignment pending count above configured threshold,
- repeated escalation count above configured threshold,
- preflight/governance inconsistency for steady-state mode.

Pause output includes:
- `paused`
- `paused_reason`
- `failure_classification`
- `recommended_human_actions`

## Scheduler guidance
Suggested schedule:
- Daily: `-Mode daily`
- Weekly: `-Mode weekly`

Use only `scripts\steady-state-run.ps1` from Task Scheduler for steady-state operations.
When watch/escalate lanes have deterministic owner acknowledgment rules, pass
`-WatchlistOwnerAckPath .\docs\steady_state_watchlist_owner_ack.json` to keep
the loop from repeatedly pausing on already-acknowledged escalation items.
