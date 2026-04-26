# Steady-State Operations Handbook

## Purpose
Define the baseline operating handbook once roadmap-driven phase delivery is complete and the repository enters steady-state commercial operations mode.

## Core operating loops

- Weekly: reliability review (`ga-weekly-reliability-review.ps1`)
- Monthly: reliability targets + closure routing (`ga-monthly-reliability-targets.ps1`, `ga-closure-sla-breach-route.ps1`)
- Quarterly: governance package (`ga-quarterly-review-package.ps1`)
- Release train: promotion/decision/notes/evidence (`release-candidate-promote.ps1` through `release-train-evidence-export.ps1`)
- Steady-state closeout: handbook/cadence/e2e package (`ga-steady-state-closeout.ps1`)
- Bounded remediation backlog: closeout-derived improvement queue (`ga-steady-state-improvement-backlog.ps1`)
- Watch backlog burn-down: open-item trend and closure pressure tracking (`ga-steady-state-burndown.ps1`)
- Cadence checkpoint refresh: monthly/quarterly/release checkpoint consolidation (`ga-steady-state-checkpoint-refresh.ps1`)
- Watchlist ownership routing: owner/status/ETA/SLA routing for watch/escalate lanes (`ga-steady-state-escalation-watchlist-route.ps1`)
- Single-entry runtime loop: daily/weekly recurring operations wrapper (`steady-state-run.ps1`)

## Required evidence roots

- `logs\operational-readiness\`
- `logs\operator-suites\`
- `logs\release-train\`
- `logs\ga-ops\`
- `logs\ga-compliance\`
- `logs\ga-steady-state\`

## Guardrails

- Keep strict auth/policy invariants unchanged.
- Keep completed-only semantics where already enforced.
- Do not expand provider scope in steady-state maintenance unless roadmap reactivation is approved.
- Preserve retention and traceability index generation in monthly/quarterly cycles.
- Keep improvement backlog changes bounded, evidence-backed, and reversible.

## Runtime loop references

- `docs/steady_state_runtime_loop.md`
- `docs/steady_state_runtime_state.json`
