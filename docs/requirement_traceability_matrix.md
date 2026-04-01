# Requirement Traceability Matrix

## Legend
- Validation status:
  - `offline-validated`
  - `staging-validated later`
  - `live-validated later`

| Req ID | Requirement | Implementation location(s) | Test coverage location(s) | Ops / readiness docs | Validation |
|---|---|---|---|---|---|
| SYS-01 | Dry-run orchestration entry point composes intake -> triage -> summary -> decision projection | `app/services/dry_run_orchestration.py` (`run_dry_run_orchestration`) | `tests/test_dry_run_orchestration.py` | `docs/system_requirements.md`, `docs/acceptance_criteria.md` | offline-validated |
| SYS-02 | Current brief artifact generation from intake result | `app/intake/review_artifacts.py`, `app/services/dry_run_orchestration.py` | `tests/test_dry_run_orchestration.py`, `tests/test_intake_review_artifacts.py` | `docs/mvp_requirements.md` | offline-validated |
| SYS-03 | GO/PAUSE/REVIEW projection with required-review/hard-gate constraints | `app/services/dry_run_orchestration.py` (`project_dry_run_decision`) | `tests/test_dry_run_orchestration.py` | `docs/system_requirements.md`, `docs/mvp_requirements.md` | offline-validated |
| SYS-04 | Projected activation decision generation | `app/services/dry_run_orchestration.py`, `app/services/activation_decision.py` | `tests/test_dry_run_orchestration.py`, `tests/test_activation_decision.py` | `docs/mvp_requirements.md` | offline-validated |
| SYS-05 | Approval record normalization from projected decision | `app/services/approval_record_builder.py`, `app/services/dry_run_orchestration.py` | `tests/test_approval_record_builder.py`, `tests/test_dry_run_orchestration.py` | `docs/mvp_requirements.md` | offline-validated |
| SYS-06 | Handoff envelope composition from projected artifacts | `app/services/dry_run_orchestration.py` (`build_dry_run_handoff_envelope*`) | `tests/test_dry_run_orchestration.py` | `docs/system_requirements.md` | offline-validated |
| SYS-07 | Receiver readiness classification / handling / action label / dispatch intent chain | `app/services/dry_run_orchestration.py` (receiver helper chain) | `tests/test_dry_run_orchestration.py` | `docs/mvp_requirements.md` | offline-validated |
| SYS-08 | Consumer and release chain (decision/mode/execution requirement/lane/clearance) | `app/services/dry_run_orchestration.py` (consumer/release helper chain) | `tests/test_dry_run_orchestration.py` | `docs/mvp_requirements.md` | offline-validated |
| SYS-09 | Unknown helper mapping values fail loudly (KeyError) | `app/services/dry_run_orchestration.py` dictionary lookups in mapping helpers | `tests/test_dry_run_orchestration.py` (unknown-value KeyError locks) | `docs/non_goals.md` | offline-validated |
| SYS-10 | Protected endpoint actor authority and precedence stability | `app/api/routes.py`, `app/services/auth.py`, `app/services/approval.py`, `app/orchestrator/service.py` | `tests/test_api.py`, `tests/test_integration_auth_approval.py`, `tests/test_manual_workflow_verification.py` | `docs/operational_startup_runbook.md` | offline-validated |
| SYS-11 | Startup/config/runtime recovery parity under env flips and app-state gaps | `app/api/main.py`, `app/api/dependencies.py`, `app/api/runtime_bindings.py` | `tests/test_runtime_startup.py`, `tests/test_api_helpers.py` | `docs/operational_startup_runbook.md` | offline-validated |
| SYS-12 | Staging rollout validation and rollback procedures documented | (documentation process requirement) | (checklist execution in staging) | `docs/staging_validation_plan.md`, `docs/live_validation_checklist.md`, `docs/rollout_plan.md`, `docs/rollback_checklist.md` | staging-validated later |
| SYS-13 | Live auth/provider/persistence verification with real credentials and infrastructure | (operational requirement; not offline code proof) | (staging/live execution required) | `docs/pre_production_requirements.md`, `docs/production_readiness_gaps.md` | live-validated later |

## Artifact coverage checklist
- `current brief` -> covered (`SYS-02`)
- `triage result` -> covered (`SYS-01`, `SYS-03`)
- `trend report` -> covered (`SYS-01`)
- `work order` -> covered (`SYS-01`)
- `management summary` -> covered (`SYS-01`)
- `projected activation decision` -> covered (`SYS-04`)
- `approval record` -> covered (`SYS-05`)
- `handoff envelope` -> covered (`SYS-06`)
