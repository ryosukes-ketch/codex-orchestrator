# Self-Serve Support-Safe Packaging

## Purpose
Define a minimal support intake package that is sufficient for incident triage while avoiding over-collection.

## Principles
- Collect manifest-first evidence before raw logs.
- Do not include secrets (`*.env`, API keys, bearer tokens, credential files).
- Keep attachments deterministic and reproducible from readiness/suite/cycle roots.
- Preserve strict policy/auth evidence context (`deny_reasons`, `audit_assert`, stage telemetry).

## Primary command

```powershell
.\scripts\self-serve-support-intake.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

Alternative source:

```powershell
.\scripts\self-serve-support-intake.ps1 -BundleManifestPath .\logs\operator-suites\<timestamp>\bundle-manifest.json -Zip
```

Underlying support-bundle collector (when detailed classification replay is needed directly):

```powershell
.\scripts\operator-support-bundle.ps1 -ReadinessManifestPath .\logs\operational-readiness\readiness-manifest-<timestamp>.json -Zip
```

## Output artifacts
- `support-intake.manifest.json`
- `support-intake.md`
- referenced `support-bundle.manifest.json`
- referenced `failure-classification.json`
- optional archive `.zip`

## Minimum attachment contract
1. support intake manifest
2. failure classification JSON
3. replay export manifest
4. readiness or suite/cycle manifest that produced the incident

## Redaction contract
- Never attach `.env` or credential files.
- Never paste bearer tokens in support notes.
- Share sqlite backups only through approved secure transfer.
- Prefer structured manifests over terminal copy-paste logs.

## Classification map
- `runtime`
- `provider_auth`
- `policy`
- `semantic_output`
- `persistence_restore`
- `operator_flow`

Use this map to choose first-response owner and escalation route.
