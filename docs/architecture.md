# Architecture

## Purpose
Build a minimal, extensible foundation for an AI work system with clear role separation:
- Intake Agent (single user-facing entry point)
- PM/Orchestrator Agent (task routing + state transitions)
- Specialist Agents (Research, Design, Build, Review, Trend)
- External trend providers (Gemini/Grok/OpenAI) via adapter interface
- Implementation/operations baseline (API, tests, config, docs)

## Current Baseline
- Repository was effectively empty at implementation start.
- No existing tech stack, docs, or constraints were detected.

## Assumptions (Explicit)
1. Language/runtime: Python 3.10+
2. Web API: FastAPI
3. Data models: Pydantic v2
4. Storage: in-memory by default, PostgreSQL repository available via env switch
5. External model keys are optional; no real key handling in code paths by default
6. Initial orchestration is deterministic/rule-based (LangGraph-compatible shape, no hard dependency)
7. Intake asks up to 3 clarifying questions per pass when required fields are missing

## Non-Goals (Current Phase)
- Full LLM prompt engineering layer
- Production auth, billing, or tenant isolation
- Real external provider API calls
- Full migration framework (Alembic etc.); schema is bootstrapped by repository initializer

## High-Level Components

### 0) Governance Departments
This repository is governed by explicit departments:
- Management Department
  - user-facing oversight, ambiguity resolution, and final approval on medium/high-risk matters
- Progress Control Department
  - applies hard gates before model judgment and decides `GO` / `PAUSE` / `REVIEW`
- Action Department
  - low-cost triage/extraction/drafting only
  - not a final authority for risky continuation
- Implementation Department
  - implements approved code/docs/tests
- Audit and Review Department
  - detects drift in auth/approval/policy/audit/security boundaries

Escalation principle:
- cheap-model confidence is not sufficient for risky continuation
- governance-sensitive tasks escalate to `REVIEW`

### 1) Intake Agent (`app/intake`)
Responsibilities:
- Accept raw user request
- Produce structured `ProjectBrief`
- Detect missing critical fields and return at most 3 clarifying questions
- Avoid over-committing unspecified requirements

Outputs:
- `IntakeResult` with:
  - normalized brief draft
  - `missing_fields`
  - `clarifying_questions` (<= 3)

### 2) PM / Orchestrator (`app/orchestrator`)
Responsibilities:
- Accept approved `ProjectBrief`
- Decompose into task units for specialist departments
- Manage status transitions, review loops, checkpoints, and approvals
- Aggregate outputs into `ProjectSummary`

Core state machine (phase: persistence + approvals):
- `draft`
- `intake_pending`
- `ready_for_planning`
- `in_progress`
- `waiting_approval`
- `review_failed`
- `revision_requested`
- `completed`

### State Transition Table
| Current | Next | Meaning |
|---|---|---|
| `draft` | `intake_pending` | Intake flow has started |
| `intake_pending` | `ready_for_planning` | Brief is accepted for planning |
| `ready_for_planning` | `in_progress` | Task execution begins |
| `in_progress` | `waiting_approval` | A gated action needs human approval |
| `waiting_approval` | `in_progress` | Approval granted, execution resumes |
| `in_progress` | `review_failed` | Review returned blocking findings |
| `review_failed` | `revision_requested` | Formal rollback request issued |
| `revision_requested` | `ready_for_planning` | Replanning lane |
| `revision_requested` | `in_progress` | Direct re-implementation lane |
| `in_progress` | `completed` | Delivery accepted |

### Stop/Resume Flow
1. Execution stops at `waiting_approval` when required action approvals are missing.
2. Human approves action set (e.g. `external_api_send`) through resume API.
3. System validates:
   - project is in `waiting_approval`
   - pending approvals are fully satisfied
   - already-approved actions are not re-approved
4. If validation passes, status returns to `in_progress` and execution resumes.
5. On review failure, project moves to `revision_requested`.
6. Revision resume API accepts explicit target mode:
   - `replanning` -> move to `ready_for_planning`
   - `rebuilding` -> move to `in_progress` and rerun build lane
   - `rereview` -> move to `in_progress` and rerun review lane
7. Approval rejection can move `waiting_approval` -> `revision_requested` with mandatory reason.
8. Replanning start API can move `ready_for_planning` -> `in_progress` explicitly.

### Approval vs Authorization
- Approval: decision that an action is allowed for a project at a given time.
- Authorization: whether a given actor is permitted to perform that approval decision.
- Both are required: approved action input is rejected unless actor authorization also passes.
- Authentication: process of verifying who the actor is before authorization.
- Actor authenticity rule: body `actor` fields are non-authoritative; server resolves actor from auth context.

### Role-to-Action Authorization Matrix (MVP)
| Action | owner | operator | approver | admin | viewer |
|---|---|---|---|---|---|
| `external_api_send` | allow | deny | allow | allow | deny |
| `destructive_change` | deny | deny | allow | allow | deny |
| `bulk_modify` | deny | allow | allow | allow | deny |
| `production_affecting_change` | deny | deny | deny | allow | deny |

Project-level allow-list support:
- API/service can accept per-action actor ID allow-lists.
- If configured, actor must satisfy both role rule and allow-list match.

### Project Policy Model
- `project_owner_actor_id`
- `strict_mode`
- per-action rules:
  - `allowed_roles`
  - `allowed_actor_ids`

Policy precedence:
1. strict mode + missing explicit action rule -> deny
2. explicit action rule -> override defaults for that action
3. no explicit rule -> fallback to default RBAC
4. runtime allow-list (if provided) can further restrict actor IDs

### 3) Specialist Departments (`app/agents`)
- `ResearchAgent`
- `DesignAgent`
- `BuildAgent`
- `ReviewAgent`
- `TrendAgent`

MVP behavior:
- deterministic placeholder implementations returning structured artifacts
- interfaces separated so future LLM workers can be swapped in without schema changes

### 4) Provider Layer (`app/providers`)
#### Requirements
- Gemini/Grok/OpenAI handled as external specialist adapters (not primary orchestrator brain)
- Common interface for trend analysis with fields:
  - `trend_topic`
  - `candidate_trends`
  - `evidence`
  - `freshness`
  - `confidence`
  - `adoption_note`

#### Strategy
- `TrendProvider` protocol/base interface
- `MockTrendProvider` as default working backend
- `GeminiTrendProvider`, `GrokTrendProvider`, `OpenAITrendProvider` as stubs with safe fallback behavior

### 5) State vs Conversation Separation (`app/state`, `app/schemas`)
Conversation and project execution state are separated:
- Conversation:
  - user messages, assistant messages, clarification turns
- Structured project state:
  - `Project`
  - `Task`
  - `Artifact`
  - `Review`
  - `Checkpoint`
  - `ApprovalRequest`

This separation enables:
- resume/restart
- audit trail
- rollback routing

### Persistence Strategy
- `ProjectRepository` interface defines persistence contract.
- `InMemoryProjectRepository` remains for local default/fallback.
- `PostgresProjectRepository` stores normalized records for:
  - `Project`
  - `Task`
  - `Artifact`
  - `Review`
  - `Checkpoint`
  - `ApprovalRequest`
  - structured history events for operation visibility
- Repository selection:
  - `STATE_BACKEND=memory` -> in-memory
  - `STATE_BACKEND=postgres` + `DATABASE_URL` -> PostgreSQL
  - invalid/missing DB config -> safe fallback to in-memory (unless strict mode enabled)

### 6) Safety Controls
- Approval-required action types are structured and explicit:
  - `external_api_send`
  - `destructive_change`
  - `bulk_modify`
  - `production_affecting_change`
- High-risk operations move project/task state to `waiting_approval` until approved
- Authorization failures are rejected and logged as audit events
- Authentication failures are rejected and logged when project context is available
- No destructive filesystem/network side effects in MVP flow
- No secret material generated, read, or committed
- `.env.example` only

### Hard Gate Rules
If any of these are touched meaningfully, autonomous continuation stops and requires `REVIEW`:
- authentication behavior
- authorization behavior
- approval flow semantics
- policy model or strict mode semantics
- actor trust model
- audit logging semantics
- database schema/migration behavior
- external provider contract
- dependency additions
- architecture direction changes

### Auditability
- History events are structured with:
  - `event_type`
  - `actor` (`actor_id`)
  - `actor_role`
  - `actor_type`
  - `timestamp`
  - `reason`
  - `metadata`
- Audit retrieval is available at project scope and includes:
  - history events
  - approvals
  - reviews
  - checkpoints
- Auth/audit coverage includes:
  - authentication success/failure
  - actor resolution
  - policy override application
  - authorization success/failure

## API Surface
- `POST /intake/brief`: parse user request into brief + clarifications
- `POST /orchestrator/run`: execute deterministic orchestration on approved brief
- `POST /orchestrator/resume/approval`: resume from `waiting_approval`
- `POST /orchestrator/approval/reject`: reject pending approval and move to revision lane
- `POST /orchestrator/resume/revision`: resume from `revision_requested`
- `POST /orchestrator/replanning/start`: start execution from `ready_for_planning`
- `GET /projects/{project_id}/audit`: retrieve history/approvals/reviews/checkpoints
- `GET /health`: liveness

### Dev Auth Strategy (Current)
- Bearer token auth for approval/reject/revision/replanning APIs.
- Token -> actor mapping is local-dev oriented and env configurable.
- Designed for later replacement by JWT/OIDC/SSO validation without changing orchestrator contracts.

## Inter-Department Handoff Contracts

### Intake -> Progress Control (Intake Output Contract)
Ownership boundary:
- Intake Department owns request clarification and draft brief normalization.
- Intake does not approve risk, does not assign final implementation authority.

Required fields:
- `request_id`
- `raw_request`
- `missing_fields` (list)
- `clarification_questions` (0..3)
- `draft_project_brief`:
  - `goal`
  - `scope_in`
  - `scope_out`
  - `constraints`
  - `acceptance_criteria`
- `readiness` (`ready_for_planning` or `needs_clarification`)

Optional fields:
- `assumptions`
- `notes`
- `suggested_next_step`

Escalation triggers:
- ambiguity remains after 3 clarification questions
- request conflicts with hard-gate boundaries (auth/approval/policy/audit/schema/dependency)
- request requires roadmap or architecture change

Example:
```json
{
  "request_id": "req_001",
  "raw_request": "Harden continuation workflow",
  "missing_fields": ["acceptance_criteria"],
  "clarification_questions": ["What is the minimum acceptance test set?"],
  "draft_project_brief": {
    "goal": "Add safe continuation checks",
    "scope_in": ["docs update", "isolated helper tests"],
    "scope_out": ["auth semantic changes"],
    "constraints": ["no dependencies"],
    "acceptance_criteria": []
  },
  "readiness": "needs_clarification"
}
```

### Progress Control -> Department Routing (Triage Output Contract)
Ownership boundary:
- Progress Control Department owns GO/PAUSE/REVIEW decisioning and escalation gating.
- Action Department can assist low-risk preprocessing only and cannot self-authorize risky continuation.

Required fields:
- `task_id`
- `risk_level` (`low` / `medium` / `high`)
- `routing_target` (`management_department` / `progress_control_department` / `action_department` / `implementation_department` / `audit_review_department`)
- `decision` (`GO` / `PAUSE` / `REVIEW`)
- `escalation_likely_required` (bool)
- `hard_gate_triggers` (list)

Optional fields:
- `escalation_reason`
- `phase_alignment`
- `verification_status`
- `notes`

Escalation triggers:
- any hard-gate trigger detected
- active roadmap phase mismatch
- cross-department scope requiring management-level arbitration
- unresolved verification instability

Example:
```json
{
  "task_id": "task_014",
  "risk_level": "high",
  "routing_target": "management_department",
  "decision": "REVIEW",
  "escalation_likely_required": true,
  "hard_gate_triggers": ["approval_flow_change"],
  "escalation_reason": "hard_gate_triggered"
}
```

### Trend Department -> Orchestrator/Implementation (Trend Output Contract)
Ownership boundary:
- Trend Department owns external-trend analysis payload quality.
- Provider adapters encapsulate Gemini/OpenAI/Grok specifics; core orchestration remains provider-agnostic.

Required fields:
- `trend_topic`
- `candidate_trends` (list of):
  - `name`
  - `confidence`
  - `freshness`
  - `adoption_note`
  - `evidence` (list of references)
- `provider_name`
- `generated_at`

Optional fields:
- `provider_metadata`
- `limitations`
- `followup_questions`

Escalation triggers:
- provider response fails contract validation
- confidence/freshness below project policy threshold
- provider output suggests external send/publish action

Example:
```json
{
  "trend_topic": "agent governance",
  "candidate_trends": [
    {
      "name": "structured escalation policies",
      "confidence": 0.82,
      "freshness": "recent",
      "adoption_note": "increasing usage in safety-sensitive workflows",
      "evidence": [{"title": "internal mock evidence", "url": "mock://evidence/1"}]
    }
  ],
  "provider_name": "mock",
  "generated_at": "2026-03-24T00:00:00Z"
}
```

### Progress Control/Orchestrator -> Implementation (Implementation Work Order Contract)
Ownership boundary:
- Implementation Department owns approved code/docs/tests changes only.
- Implementation cannot override hard-gate outcomes; REVIEW stays blocked until Management/Audit decision.

Required fields:
- `work_order_id`
- `project_id`
- `objective`
- `in_scope`
- `out_of_scope`
- `constraints`
- `decision_context`:
  - `decision` (`GO` only for autonomous execution)
  - `risk_level`
  - `hard_gate_triggers`
- `verification_plan`
- `done_criteria`

Optional fields:
- `recommended_files`
- `rollback_notes`
- `handoff_notes`

Escalation triggers:
- work order conflicts with `direction_guard` or active phase
- hidden dependency/schema/auth/policy/audit changes emerge during implementation
- verification fails twice without clearly local fix

Example:
```json
{
  "work_order_id": "wo_20260324_01",
  "project_id": "proj_001",
  "objective": "Document inter-department handoff contracts",
  "in_scope": ["docs/architecture.md", "docs/implementation-plan.md"],
  "out_of_scope": ["runtime behavior changes"],
  "constraints": ["no dependencies", "no auth semantics change"],
  "decision_context": {
    "decision": "GO",
    "risk_level": "low",
    "hard_gate_triggers": []
  },
  "verification_plan": ["minimal doc consistency check"],
  "done_criteria": ["contracts documented with escalation boundaries"]
}
```

## Extensibility Notes
- Provider adapters can be replaced independently.
- State repository can be switched from in-memory to PostgreSQL without API/schema break.
- Agent implementations can move from deterministic placeholders to model-backed workers incrementally.
- Schema bootstrap can be replaced with full migration tooling later without repository contract changes.
