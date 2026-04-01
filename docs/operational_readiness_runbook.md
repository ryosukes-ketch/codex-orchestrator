# Operational Readiness Runbook

## 1. Primary command

Use this command as the default operational gate before starting work or shipping changes.

```powershell
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
```

## 2. Pass criteria

All of the following must pass:

- Preflight
- Live smoke with automatic seeds
- Approval live flow
- Reject -> Revision -> Replanning live flow
- Smoke
- Resilience
- Full verification
- Final output ends with `All checks passed!`

## 3. When to run

- Before starting operational work
- After changes to orchestrator, API, auth, approval, revision, replanning, or readiness scripts
- Before merging significant changes to `master`
- After merging to `master` when extra safety is desired

## 4. Fail handling

If any stage fails, treat the environment as not ready.

Check in this order:

1. `/health` returns `ok`
2. Local API server is running
3. Authorization value is correct
4. Which stage failed: Preflight / Live smoke / Smoke / Resilience / Full verification
5. What changed immediately before the failure

Do not continue with operational work until the same readiness command passes end-to-end.

## 5. Logs

Operational logs are written under `logs/operational-readiness/`.

- Treat them as generated runtime output
- Do not commit them to Git
- Check the newest seed log and live-smoke log first when investigating a failure

## 6. Daily-use commands

```powershell
.\scripts\preflight.ps1
.\scripts\live-smoke.ps1
.\scripts\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
```

## 7. Operational decision rule

Use this single rule:

- If `release-readiness.ps1 -AutoSeedFullFlow` passes, the environment is ready
- If it fails, the environment is not ready

## 8. Current baseline

- Branch baseline: `master`
- Logs are ignored in Git
- Readiness includes automatic seed creation for approval and reject/revision/replanning live paths
