# Phase 20 Environment Compatibility and Support-at-Scale Baseline

## Purpose
Define the supported environment matrix, execute deterministic compatibility preflight checks, and normalize support intake artifacts for larger commercial operations volume.

## Commands

```powershell
.\scripts\ga-supported-environment-matrix.ps1 -Zip
.\scripts\ga-compatibility-preflight.ps1 -Zip
.\scripts\ga-support-intake-normalization.ps1 -Zip
.\scripts\ga-environment-support-closeout.ps1 -Zip
```

## Output contracts

### 1) Supported environment matrix

- script: `scripts/ga-supported-environment-matrix.ps1`
- `bundle_type`: `phase20_supported_environment_matrix`
- core summary fields:
  - `supported_environment_count`
  - `unsupported_environment_count`
  - `compatibility_baseline_decision`

### 2) Compatibility preflight report

- script: `scripts/ga-compatibility-preflight.ps1`
- `bundle_type`: `phase20_compatibility_preflight_report`
- core summary fields:
  - `required_check_count`
  - `failed_required_check_count`
  - `failed_optional_check_count`
  - `compatibility_decision`
- core details fields:
  - `check_results`
  - `missing_scripts`

### 3) Support intake normalization

- script: `scripts/ga-support-intake-normalization.ps1`
- `bundle_type`: `phase20_support_intake_normalization`
- core summary fields:
  - `support_intake_manifest_count`
  - `blocking_manifest_count`
  - `missing_required_field_count`
  - `normalization_decision`
- core details fields:
  - `required_fields`
  - `classification_status_counts`
  - `category_counts`
  - `severity_counts`

### 4) Environment/support closeout

- script: `scripts/ga-environment-support-closeout.ps1`
- `bundle_type`: `phase20_environment_support_closeout`
- core summary fields:
  - `matrix_decision`
  - `compatibility_decision`
  - `support_normalization_decision`
  - `closeout_decision`
- source manifest fields:
  - `matrix_manifest_path`
  - `compatibility_manifest_path`
  - `support_normalization_manifest_path`

## Decision vocabulary

- `go`
  - matrix, preflight, and support-intake normalization packages are healthy.
- `watch`
  - no hard blockers, but one or more packages still need bounded follow-up.
- `escalate`
  - required compatibility checks or intake normalization guarantees are not met.

## Phase 20 evidence closure guidance

Retain:

- `ga-supported-environment-matrix.manifest.json`
- `ga-compatibility-preflight.manifest.json`
- `ga-support-intake-normalization.manifest.json`
- `phase20-environment-support-closeout.manifest.json`
- one phase_20 evidence entry in `docs/staging_execution_record.md`

