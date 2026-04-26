# Self-Serve Product Acceptance Checklist

## Goal
Confirm the repository is packaged for customer-managed self-serve operation without relaxing strict policy/auth controls.

## Checklist
- [ ] `self-serve-preflight.ps1` passes with target `.env`.
- [ ] `self-serve-update-guard.ps1` produced sqlite verify/backup/export manifests.
- [ ] strict `scripts/ai_work_system/release-readiness.ps1` completed (`All checks passed!`).
- [ ] `self-serve-support-intake.ps1` produced support intake + classification artifacts.
- [ ] `self-serve-handoff-package.ps1` returned `acceptance_status=ready_for_handoff`.
- [ ] `README.md` and runbooks reference phase_10 self-serve scripts/docs.
- [ ] `python -m ruff check app` passes.
- [ ] `python -m ruff check tests` passes.
- [ ] `python -m pytest -q tests` passes.

## Evidence paths to capture
- self-serve preflight JSON
- update-guard manifest
- readiness summary + readiness manifest
- support-intake manifest
- handoff-package manifest

## Notes
- Keep strict completed-only semantics.
- Do not relax policy/auth assertions for acceptance runs.
- If acceptance fails, classify using `failure-classification.json` before changing code.
