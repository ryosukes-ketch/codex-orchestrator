# Phase 21 Auditability, Retention, and Compliance-lite Governance

## Purpose
Standardize artifact retention/export coverage, traceability indexing, and incident/change ledgers so support, release, and operations evidence can be audited consistently.

## Commands

```powershell
.\scripts\ga-artifact-retention-coverage.ps1 -Zip
.\scripts\ga-audit-traceability-index.ps1 -Zip
.\scripts\ga-incident-change-ledger.ps1 -Zip
.\scripts\ga-auditability-closeout.ps1 -Zip
```

## Output contracts

### 1) Artifact retention/export coverage

- script: `scripts/ga-artifact-retention-coverage.ps1`
- `bundle_type`: `phase21_artifact_retention_export_coverage`
- core summary fields:
  - `artifact_family_count`
  - `missing_required_coverage_count`
  - `retention_decision`

### 2) Audit traceability index

- script: `scripts/ga-audit-traceability-index.ps1`
- `bundle_type`: `phase21_audit_traceability_index`
- core summary fields:
  - `trace_entry_count`
  - `missing_required_trace_count`
  - `traceability_decision`
- core details fields:
  - `required_trace_types`
  - `trace_entries`

### 3) Incident/change ledger package

- script: `scripts/ga-incident-change-ledger.ps1`
- `bundle_type`: `phase21_incident_change_ledger`
- core summary fields:
  - `incident_entry_count`
  - `change_entry_count`
  - `ledger_decision`
- core details fields:
  - `entries`

### 4) Auditability closeout

- script: `scripts/ga-auditability-closeout.ps1`
- `bundle_type`: `phase21_auditability_closeout`
- core summary fields:
  - `retention_decision`
  - `traceability_decision`
  - `ledger_decision`
  - `closeout_decision`

## Decision vocabulary

- `go`
  - retention, traceability, and ledger artifacts are complete.
- `watch`
  - one or more coverage/traceability/ledger gaps still require follow-up.
- `escalate`
  - required compliance-lite evidence prerequisites are missing.

## Phase 21 evidence closure guidance

Retain:

- `ga-artifact-retention-coverage.manifest.json`
- `ga-audit-traceability-index.manifest.json`
- `ga-incident-change-ledger.manifest.json`
- `phase21-auditability-closeout.manifest.json`
- one phase_21 evidence entry in `docs/staging_execution_record.md`

