# Phase 15 Hotfix and Next-Release Routing (p15_t3)

## Purpose
Convert early-operations recurring hardening signals into deterministic routing lanes:
- hotfix candidate
- next-release candidate
- runbook patch
- monitoring/defer

## Command
```powershell
.\scripts\hotfix-next-release-route.ps1
```

## Output
- `phase15_hotfix_next_release_routing` manifest
- routing summary JSON/Markdown
- refreshed phase13 artifacts:
  - post-launch triage
  - post-launch priority scoring
  - known issue routing
  - post-launch backlog export

## Acceptance
- Hotfix and next-release counts are explicit in summary.
- Routing rationale is auditable from generated manifests.
- Known-issue routing remains synchronized with release backlog lanes.
