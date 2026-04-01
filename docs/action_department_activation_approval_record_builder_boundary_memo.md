# Action Department Approval Record Builder Implementation Boundary Memo

## Purpose
Define the smallest approved implementation boundary for an offline builder that
converts projected activation decisions into approval record artifacts.

This memo is planning-only.
It does not authorize runtime activation, provider execution, or policy wiring changes.

## Scope
This boundary applies only to dry-run/offline artifact generation in repository workflows.

In scope:
- deterministic conversion from normalized management-side inputs
- `GO` / `PAUSE` / `REVIEW` approval-record artifact generation
- governance-critical field preservation from projected activation decision

Out of scope:
- live provider activation
- runtime control-path decisions
- auth/policy framework wiring changes
- schema renames or field churn

## Proposed Builder Boundary
Builder role (private/internal):
- Input: projected activation decision and related management context already normalized
- Output: approval record artifact aligned to `docs/action_department_activation_approval_record_format.md`

Minimum input contract:
- projected decision fields:
  - `activation_target`
  - `activation_scope`
  - `recommendation`
  - `remaining_blockers`
  - `re_review_required`
  - `escalation_destination`
  - `human_approvals_recorded`
  - `autonomous_continuation_status`
  - `autonomous_continuation_note`
  - `rollback_disable_expectation`
- related ids/context when available:
  - review item id / project id / packet id / queue item id
  - management reviewer metadata and rationale

Minimum output contract:
- approval record fields required by format doc:
  - `activation_review_item_id`
  - `activation_target`
  - `activation_scope`
  - `human_approval_status`
  - `management_review_status`
  - `recommendation`
  - `autonomous_continuation_status`
  - `retained_constraints`
  - `rollback_disable_expectation`
  - `follow_up_actions_before_broader_live_use`

## Decision Handling Rules
`GO`:
- preserve bounded scope only
- preserve retained constraints
- preserve autonomous continuation as separately governed

`PAUSE`:
- preserve blocker retention
- preserve re-review requirement before continuation
- keep activation disabled until blockers clear

`REVIEW`:
- preserve explicit escalation destination
- preserve blocker-driven review outcome
- keep activation disabled pending escalation outcome

## Governance-Critical Invariants
- Activation approval and autonomous continuation approval are separate decisions.
- Autonomous continuation remains not approved unless explicitly approved through the required governance process.
- Unresolved blockers prevent activation from continuing.
- REVIEW paths must carry an explicit escalation destination.
- Latest-alias outputs remain advisory-only for risky/governance-sensitive work.

## Non-Goals for the Next Implementation Batch
- no approval semantics expansion beyond current docs/examples
- no orchestration behavior change
- no new external interfaces (CLI/API) unless explicitly approved in a later batch
- no automatic live activation side effects

## Alignment References
- `docs/action_department_activation_decision_format.md`
- `docs/action_department_activation_approval_record_format.md`
- `docs/examples/action_department_activation_approval_record_example.json`
- `docs/examples/action_department_activation_approval_record_pause_example.json`
- `docs/examples/action_department_activation_approval_record_review_example.json`
