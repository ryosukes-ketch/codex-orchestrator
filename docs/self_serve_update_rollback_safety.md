# Self-Serve Update and Rollback Safety

## Purpose
Define safe update/rollback behavior for customer-managed installations.

## Data safety rules
- Always create sqlite backup before update (`scripts/sqlite-backup.ps1`).
- Keep readiness and suite manifests from the pre-update run.
- Keep support bundle artifacts for failed updates.

## Update sequence
```powershell
.\scripts\sqlite-verify.ps1
.\scripts\sqlite-backup.ps1 -Label pre-update
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
.\scripts\self-serve-update-guard.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Rollback trigger examples
- strict readiness regression after update
- support classification indicates `persistence_restore` or unresolved `runtime` blocker

## Rollback sequence
```powershell
.\scripts\sqlite-restore.ps1 -BackupManifestPath .\logs\sqlite-backups\<backup>.manifest.json -Force
.\scripts\sqlite-verify.ps1
.\scripts\ai_work_system\release-readiness.ps1 -AutoSeedFullFlow -Authorization "Bearer dev-approver-token"
```

## Evidence retention minimum
- pre-update backup manifest
- post-update readiness manifest
- rollback readiness manifest (if rollback executed)
- support-bundle manifest for incident handoff

## Constraints
- Do not delete historical readiness/suite manifests during rollback.
- Do not run restore while API server is active.
- Keep `update-guard.manifest.json` with backup/export manifests before any version bump.
