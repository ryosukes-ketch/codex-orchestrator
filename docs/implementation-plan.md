# Implementation Plan

## Objective
Deliver a runnable minimum scaffold with clear boundaries and safe defaults.

## Governance Execution Model
- Department model is mandatory:
  - Management Department
  - Progress Control Department
  - Action Department
  - Implementation Department
  - Audit and Review Department
- Progress Control applies hard gates first, then selects one decision:
  - `GO`
  - `PAUSE`
  - `REVIEW`
- Action Department support is allowed for low-risk drafting, but it cannot self-authorize risky continuation.

## Phases

### Phase 0 - Repository Survey (Done)
- Found empty baseline
- No conflicting stack detected

### Phase 1 - Critical Blockers (Done)
- No hard blockers
- Proceed under explicit assumptions documented in `docs/architecture.md`

### Phase 2 - Design Lock (This phase)
Deliverables:
- `docs/architecture.md`
- `docs/implementation-plan.md`

Acceptance:
- Intake/Orchestrator/Departments/Providers/State boundaries are explicit
- Assumptions and non-goals are explicit

### Phase 3 - Core Scaffold
Deliverables:
- `app/` package layout
- Pydantic schemas for brief, project/task/artifact/review/checkpoint, trend payloads
- provider interface and adapters (mock + stubs)
- intake minimal logic (missing fields + max 3 clarifying questions)
- orchestrator minimal workflow and state transitions
- specialist department placeholder agents

Acceptance:
- Can run orchestration end-to-end using mock provider with no external keys

### Phase 4 - API + Tests + Ops Basics
Deliverables:
- FastAPI app + routes
- pytest minimal tests (intake, orchestrator, provider contract, health endpoint)
- `README.md` with setup/run/test instructions and extension strategy
- `.env.example`
- `pyproject.toml` with minimal dependencies

Acceptance:
- `pytest` passes locally
- `uvicorn` can serve endpoints

### Phase 5 - Persistence and Approval Foundation
Deliverables:
- repository contract cleanup and implementation split:
  - in-memory implementation
  - PostgreSQL implementation
  - env-based repository factory with fallback
- structured approval policy + typed action categories
- orchestrator state lifecycle update with rollback-friendly transitions
- docs update for transition model and approval gates
- tests for repository/approval/transitions

Acceptance:
- DB not configured: system still runs using in-memory repository
- DB configured: records are persisted/reloaded through PostgreSQL repository
- approval-required actions can put project into `waiting_approval`
- review-failed path can enter `revision_requested` and return to planning lane

### Phase 6 - Final Consolidation
Deliverables:
- concise implementation summary
- assumptions list
- known gaps
- next priorities
- human-approval-required operations list

### Phase 7 - Safe Resume Foundation
Deliverables:
- approval-resume API with strict state/action validation
- revision-resume API with explicit resume modes:
  - `replanning`
  - `rebuilding`
  - `rereview`
- project audit retrieval API for:
  - history events
  - approvals
  - reviews
  - checkpoints
- structured history events (`event_type`, `actor`, `timestamp`, `reason`, `metadata`)
- tests for valid/invalid resume behavior and history recording

Acceptance:
- project in non-`waiting_approval` state cannot be resumed by approval endpoint
- insufficient or duplicate approval input is rejected
- `revision_requested` resume path records reason and transition history
- audit endpoint returns consistent structured data from repository-backed state

### Phase 8 - Authorization + Explicit Replanning Entry
Deliverables:
- actor model with role/type context in resume/approval APIs
- role-based authorization checks per approval action
- explicit approval rejection flow with reason
- explicit replanning start API for `ready_for_planning` state
- authorization failure audit events
- tests for role matrix, reject flow, and replanning start

Acceptance:
- unauthorized actor gets explicit reject response
- authorization failure is persisted in audit events
- approval rejection transitions to `revision_requested` with reason logged
- replanning start is allowed only from `ready_for_planning`

### Phase 9 - Authentication + Actor Authenticity + Project Policy
Deliverables:
- dev-friendly minimal authentication (bearer token mapping)
- server-side actor resolution from auth context
- approval/reject/replanning/revision APIs enforced as authenticated endpoints
- project policy schema:
  - owner
  - strict_mode
  - action-level roles and actor IDs
- policy precedence wired into authorization checks
- audit events for:
  - authentication success/failure
  - actor resolved
  - policy override applied
  - authorization success/failure

Acceptance:
- unauthenticated requests to protected endpoints are rejected
- body actor tampering does not escalate privileges
- strict project policy behaves deterministically
- audit endpoint reflects auth/authz and policy decisions

## Minimal File Roadmap
1. Docs and config
2. Schemas
3. Provider interfaces/adapters
4. Intake
5. Orchestrator + agents
6. API
7. Tests
8. Readme

## Risks and Mitigations
- Risk: over-abstraction too early
  - Mitigation: deterministic, thin interfaces only
- Risk: provider coupling
  - Mitigation: strict protocol + typed trend result schema
- Risk: hidden state/conversation coupling
  - Mitigation: separate schemas and state repository
- Risk: cheap-model optimism bypassing governance
  - Mitigation: enforce hard-gate escalation and explicit `GO/PAUSE/REVIEW` decisions

## Approval Model (Current)
- Action taxonomy:
  - `external_api_send`
  - `destructive_change`
  - `bulk_modify`
  - `production_affecting_change`
- Default policy: all taxonomy actions are human approval required.
- Execution behavior:
  - if required action is not approved, execution transitions to `waiting_approval`
  - once approved, the same workflow can continue from `in_progress`

## Resume Rules (Current)
- Approval resume:
  - allowed only when project status is `waiting_approval`
  - all pending approval actions must be supplied
  - already approved actions cannot be approved again
- Revision resume:
  - allowed only when project status is `revision_requested`
  - resume mode is mandatory (`replanning`/`rebuilding`/`rereview`)
  - reason and actor are logged to structured history

## Authorization Rules (Current)
- Actor context:
  - `actor_id`
  - `actor_role`
  - `actor_type`
- Approval action authorization:
  - `external_api_send`: owner/approver/admin
  - `destructive_change`: approver/admin
  - `bulk_modify`: operator/approver/admin
  - `production_affecting_change`: admin only
- Optional project-level allow-list can further restrict actor IDs per action.

## Authentication Rules (Current)
- Protected endpoints:
  - `POST /orchestrator/resume/approval`
  - `POST /orchestrator/approval/reject`
  - `POST /orchestrator/resume/revision`
  - `POST /orchestrator/replanning/start`
- Actor is resolved from bearer token, not request body actor fields.
- Authentication failures return 401 and are logged when project context is available.

## Escalation Rules (Current)
- `GO` only when scope is phase-aligned, low-risk, and does not cross hard gates.
- `PAUSE` when local blockers or unclear next step prevent safe continuation.
- `REVIEW` when auth/approval/policy/audit/security/schema/dependency/direction boundaries are touched.

## Inter-Department Handoff Contract Checklist (Current)
Use this checklist before cross-department routing so ownership boundaries stay explicit.

### 1) Intake Output
- Owner: Intake Department
- Required: `request_id`, `raw_request`, `missing_fields`, `clarification_questions` (max 3), `draft_project_brief`, `readiness`
- Optional: assumptions, notes, suggested next step
- Escalate to `REVIEW` if ambiguity remains after max clarification pass or hard-gate areas are implicated

### 2) Progress Control Triage Output
- Owner: Progress Control Department
- Required: `task_id`, `risk_level`, `routing_target`, `decision`, `escalation_likely_required`, `hard_gate_triggers`
- Optional: escalation reason, phase alignment note, verification note
- Guardrail: Action Department can assist low-risk drafting/classification, but cannot self-authorize risky continuation

### 3) Trend Output
- Owner: Trend Department (provider adapters behind interface)
- Required: `trend_topic`, `candidate_trends` with `confidence`/`freshness`/`adoption_note`/`evidence`, `provider_name`, `generated_at`
- Optional: provider metadata, limitations, follow-up questions
- Escalate when contract validation fails or output implies external send/publish risk

### 4) Implementation Work Order Input
- Owner: Progress Control + Orchestrator (issued), Implementation Department (executed)
- Required: `work_order_id`, `project_id`, `objective`, `in_scope`, `out_of_scope`, `constraints`, `decision_context`, `verification_plan`, `done_criteria`
- Optional: recommended files, rollback notes, handoff notes
- Execution rule: autonomous implementation proceeds only when `decision_context.decision == GO`
- Escalate immediately if hidden hard-gate triggers appear during implementation

## Migration Path
- Current DB initializer creates required tables if missing.
- Future migration tool integration (e.g. Alembic) should preserve:
  - `ProjectRepository` contract
  - schema field compatibility for `ProjectRecord` components
