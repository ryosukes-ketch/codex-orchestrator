# Commercial Pilot Support Runbook

## Purpose
Provide a deterministic first-response playbook for pilot incidents.

## Inputs required for first response
- Readiness manifest path (`readiness-manifest-<timestamp>.json`)
- Bundle manifest path (`bundle-manifest.json`) if available
- Support bundle output (`support-bundle.manifest.json`)
- Time of failure and operator command line used

## First-response flow
1. Confirm startup and gateway health
   - `scripts\openclaw-gateway-check.ps1`
2. Confirm strict gate result source
   - `operator_suite_stage_gate` in readiness summary/manifest
3. Export support bundle if missing
   - `scripts\operator-support-bundle.ps1`
4. Classify by `failure-classification.json`
5. Route to owner by category

## Category routing map
- `runtime`
  - owner: runtime operations
  - check: endpoint timeout, gateway health, uvicorn process
- `provider_auth`
  - owner: provider credentials owner
  - check: upstream rejection, token refresh, credit limits
- `policy`
  - owner: policy/auth owner
  - check: allowlist mismatch, auth evidence, override mismatch, breakglass evidence
- `semantic_output`
  - owner: model/runtime owner
  - check: non-JSON output, missing required keys, unstable review decision
- `persistence_restore`
  - owner: persistence owner
  - check: sqlite verify/backup/restore/export path
- `operator_flow`
  - owner: workflow owner
  - check: state transition mismatch, replay mismatch

## Mandatory artifact collection
Use one of the following:

```powershell
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
.\scripts\operator-support-bundle.ps1 -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json -Zip
```

## Escalation package minimum
- `support-bundle.manifest.json`
- `failure-classification.json`
- `failure-classification.md`
- command transcript (exact command + time)
- latest `openclaw-gateway-check` evidence (if OpenClaw path involved)

## Customer communication template reference
Use `docs/commercial_pilot_inquiry_template.md` for deterministic intake.

## Post-launch feedback loop (phase_12)
Convert recent support bundles into deterministic runbook delta candidates:

```powershell
.\scripts\launch-week-trend-review.ps1 -WindowDays 7
.\scripts\support-recurring-hardening.ps1
```

Review outputs:
- `docs/launch_week_support_trend_review.md`
- `docs/launch_week_runbook_delta_backlog.md`
- `docs/phase12_recurring_issue_hardening.md`

## Post-launch backlog operationalization (phase_13)
Convert hardening outputs into triage, scoring, routing, and release backlog evidence:

```powershell
.\scripts\post-launch-triage.ps1
.\scripts\post-launch-priority-score.ps1
.\scripts\known-issue-route.ps1
.\scripts\post-launch-backlog-export.ps1
```

Review outputs:
- `docs/post_launch_issue_triage.md`
- `docs/post_launch_priority_scoring.md`
- `docs/known_issue_routing.md`
- `docs/post_launch_release_backlog_flow.md`

## Release-train output routing (phase_14)

Convert release backlog candidates into shipment decision + publication artifacts:

```powershell
.\scripts\release-candidate-promote.ps1
.\scripts\release-decision-package.ps1
.\scripts\release-notes-assemble.ps1
.\scripts\known-issue-publication-route.ps1
.\scripts\release-train-evidence-export.ps1 -Zip
```

Release-train docs:
- `docs/release_candidate_promotion.md`
- `docs/release_go_hold_rollback_decision.md`
- `docs/release_note_publication_flow.md`
- `docs/release_train_evidence_flow.md`

## Phase 15 launch execution baseline

```powershell
.\scripts\ga-launch-package-execute.ps1 -Zip
.\scripts\early-ops-incident-loop.ps1 -WindowDays 7
.\scripts\hotfix-next-release-route.ps1
.\scripts\phase15-evidence-closeout.ps1 -Zip
```

Docs:
- `docs/ga_launch_execution_baseline.md`
- `docs/phase15_early_operations_stabilization.md`
- `docs/phase15_hotfix_next_release_routing.md`
- `docs/phase15_evidence_closure.md`
