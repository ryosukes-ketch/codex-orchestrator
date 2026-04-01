# AI Work System Scaffold

Minimal foundation for a role-separated AI work system:
- Intake Agent (single user-facing window)
- PM Orchestrator
- Specialist departments (Research, Design, Build, Review, Trend)
- External trend adapters (OpenAI, Gemini, Grok) as provider interfaces
- Safe-by-default operations with mock fallback

## Why this repo
This scaffold prioritizes:
- clear responsibility boundaries
- state/conversation separation
- testability and future extension
- easy handoff to other coding agents

## Department-Based Governance Model
This repository is operated as a department-based AI organization, not a single freeform agent.

- Management Department
  - owns user communication, ambiguity resolution, and medium/high-risk final approval
- Progress Control Department
  - applies hard gates first and decides `GO` / `PAUSE` / `REVIEW`
- Action Department
  - low-cost support for extraction/classification/drafting only
  - cannot self-authorize risky continuation
- Implementation Department
  - performs approved code/docs/test changes
- Audit and Review Department
  - checks drift in auth/approval/policy/audit boundaries

Hard-gate-sensitive work (auth, approval, policy, audit semantics, schema/migration, dependencies,
security boundaries, architecture direction) must escalate to `REVIEW`.

## Project structure
```text
app/
  intake/
  orchestrator/
  agents/
  providers/
  schemas/
  state/
  services/
  api/
tests/
docs/
```

## Quick start
1. Create and activate a virtual environment.
2. Install:
   - runtime: `pip install -e .`
   - dev: `pip install -e .[dev]`
   - with PostgreSQL support: `pip install -e .[postgres,dev]`
3. Run API:
   - `uvicorn app.api.main:app --reload`
4. Run tests:
   - `pytest`

## State backend switch
- Default: in-memory (`STATE_BACKEND=memory`)
- PostgreSQL: set `STATE_BACKEND=postgres` and `DATABASE_URL`
- Fallback behavior:
  - when `STATE_BACKEND=postgres` but DB config/connection is unavailable,
    repository falls back to in-memory unless `STATE_BACKEND_STRICT=true`
  - malformed `STATE_BACKEND_STRICT` values fail-safe to strict behavior

## Trend provider strictness
- `TREND_PROVIDER_STRICT=false` (default):
  - unknown provider names fall back to `mock`
- `TREND_PROVIDER_STRICT=true`:
  - unknown provider names return conflict (`409`)
- malformed `TREND_PROVIDER_STRICT` values fail-safe to strict behavior

## Dev authentication
- Approval/Reject/Revision/Replanning APIs are authentication-required.
- Auth source: `Authorization: Bearer <token>`.
- Actor is resolved server-side from token; body `actor` is accepted for compatibility but not trusted.
- Default dev tokens:
  - `dev-owner-token`
  - `dev-operator-token`
  - `dev-approver-token`
  - `dev-admin-token`
  - `dev-viewer-token`
- Override with `DEV_AUTH_TOKEN_SEED` in `.env`.

## Minimal API
- `GET /health`
- `POST /intake/brief`
- `POST /orchestrator/run`
- `POST /orchestrator/resume/approval`
- `POST /orchestrator/approval/reject`
- `POST /orchestrator/resume/revision`
- `POST /orchestrator/replanning/start`
- `GET /projects/{project_id}/audit`

### Example intake request
```bash
curl -X POST http://127.0.0.1:8000/intake/brief \
  -H "Content-Type: application/json" \
  -d "{\"user_request\":\"Build an AI internal delivery platform\"}"
```

### Example orchestration request
Use the `brief` returned by intake and send it to:
`POST /orchestrator/run` with optional `"trend_provider": "mock|openai|gemini|grok"`.

When using external trend providers (`openai/gemini/grok`), orchestration can enter
`waiting_approval` unless `"approved_actions": ["external_api_send"]` is provided.

### Approval-required actions
- `external_api_send`
- `destructive_change`
- `bulk_modify`
- `production_affecting_change`

### Authorization (RBAC, MVP)
- Roles:
  - `owner`
  - `operator`
  - `approver`
  - `admin`
  - `viewer`
- Rules:
  - `viewer` cannot approve
  - `approver` and `admin` can approve high-risk actions
  - `production_affecting_change` is `admin` only
- optional project-level actor allow-list can add per-project restrictions

### Project policy precedence
1. If `project_policy.strict_mode=true` and no explicit rule for the action: deny.
2. If explicit action rule exists in project policy:
   - use `allowed_roles`
   - apply `allowed_actor_ids` when present
3. Otherwise, fallback to default RBAC rule.
4. Runtime allow-list (if provided by service flow) can further restrict actor IDs.

### Stop and resume
1. Run orchestration with external provider:
   - it may stop at `waiting_approval`
2. Resume with approval endpoint:
   - provide `project_id` + `approved_actions`
   - optional `actor` and `note`
3. If review fails, project can enter `revision_requested`
4. Resume revision with explicit mode:
   - `replanning`
   - `rebuilding`
   - `rereview`

### Example: resume from waiting_approval
```bash
curl -X POST http://127.0.0.1:8000/orchestrator/resume/approval \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-approver-token" \
  -d "{\"project_id\":\"<id>\",\"approved_actions\":[\"external_api_send\"],\"actor\":{\"actor_id\":\"u-1\",\"actor_role\":\"approver\",\"actor_type\":\"human\"}}"
```

### Example: reject approval
```bash
curl -X POST http://127.0.0.1:8000/orchestrator/approval/reject \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-approver-token" \
  -d "{\"project_id\":\"<id>\",\"rejected_actions\":[\"external_api_send\"],\"actor\":{\"actor_id\":\"u-2\",\"actor_role\":\"approver\",\"actor_type\":\"human\"},\"reason\":\"Security policy\"}"
```

### Example: resume from revision_requested
```bash
curl -X POST http://127.0.0.1:8000/orchestrator/resume/revision \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-operator-token" \
  -d "{\"project_id\":\"<id>\",\"resume_mode\":\"replanning\",\"actor\":{\"actor_id\":\"u-3\",\"actor_role\":\"operator\",\"actor_type\":\"human\"},\"reason\":\"Adjust architecture\"}"
```

### Example: start replanning execution
```bash
curl -X POST http://127.0.0.1:8000/orchestrator/replanning/start \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-operator-token" \
  -d "{\"project_id\":\"<id>\",\"actor\":{\"actor_id\":\"u-3\",\"actor_role\":\"operator\",\"actor_type\":\"human\"},\"note\":\"Start revised plan\"}"
```

### Example: audit retrieval
```bash
curl http://127.0.0.1:8000/projects/<id>/audit
```

## Design docs
- `docs/architecture.md`
- `docs/implementation-plan.md`
- `docs/operational_startup_runbook.md`
- `docs/system_requirements.md`
- `docs/mvp_requirements.md`
- `docs/pre_production_requirements.md`
- `docs/non_goals.md`
- `docs/requirement_traceability_matrix.md`
- `docs/acceptance_criteria.md`
- `docs/staging_validation_plan.md`
- `docs/staging_execution_record.md`
- `docs/staging_evidence_template.md`
- `docs/staging_issue_triage_template.md`
- `docs/staging_signoff_template.md`
- `docs/live_validation_checklist.md`
- `docs/rollout_plan.md`
- `docs/rollback_checklist.md`
- `docs/production_readiness_gaps.md`

## Management Review Artifacts
- `docs/management_review_template.md`
- `docs/management_department_runbook.md`
- `docs/management_department_prompt.md`
- `docs/examples/management_review_session_example.md`
- `docs/management_readiness_checklist.md`
- `docs/management_decision_format.md`
- `docs/review_queue_format.md`
- `docs/examples/review_queue_item_example.json`
- `docs/examples/management_decision_example.json`
- `docs/current_brief_template.json`
- `docs/current_work_order_template.json`
- `docs/review_decision_template.md`

## Codex Continuation Automation
- `docs/codex_continuation_runbook.md`
- `docs/codex_automation_prompts.md`
- `docs/model_governance_policy.md`
- `docs/model_routing_policy.json`

## Continuation Decision Rules
Use these values when deciding whether to proceed with the next implementation step:

- `GO`
  - task is inside active roadmap phase
  - no architecture/direction change is needed
  - no new dependency is needed
  - no auth/approval/policy/security redesign is needed
  - smallest relevant verification passes

- `PAUSE`
  - local verification fails and root cause is not isolated
  - next valid step is unclear from roadmap/direction guard
  - continuing now would likely create unsafe or unclear changes

- `REVIEW`
  - roadmap/phase update is required
  - dependency addition is required
  - migration or significant auth/approval/policy change is required
  - direction conflict is detected

## Escalation Rules
- Low-risk tasks (docs wording, local formatting, narrow tests) may continue with `GO`.
- Medium-risk tasks (multi-file behavior changes, orchestration behavior shifts) require conservative judgment;
  if behavior may drift, escalate to `REVIEW`.
- High-risk tasks (auth/approval/policy/audit/security/schema/dependency changes) are `REVIEW` by default.
- Cheap action models may assist with drafting, but cannot be final authority for risky continuation.

## Extension strategy
1. Replace dev token auth with JWT/OIDC/SSO verification.
2. Add real provider API clients behind existing provider adapters.
3. Move DB bootstrap SQL to managed migrations (Alembic).
4. Add retrieval and evidence freshness scoring (pgvector-ready path).

## Safety
- No real secrets are stored or required for baseline operation.
- `.env.example` only; real keys are optional and not used by default flow.

## Local verification

```powershell
.\scripts\verify.ps1
.\scripts\verify.ps1 -ApiOnly
.\scripts\verify.ps1 -NoRuff
.\scripts\verify.ps1 -ApiOnly -NoRuff
```

## Operational readiness

Run the service first, then use these commands:

```powershell
.\scripts\preflight.ps1
.\scripts\live-smoke.ps1
.\scripts\live-smoke.ps1 -ProjectId your-project-id
.\scripts\smoke.ps1
.\scripts\resilience.ps1
.\scripts\release-readiness.ps1
.\scripts\release-readiness.ps1 -ProjectId your-project-id
.\scripts\release-readiness.ps1 -SkipVerify
```


