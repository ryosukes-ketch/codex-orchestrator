# Action Department Limited-Live Activation Flow (Manual)

## Purpose
Document the manual pre-activation review flow for limited live provider use in Action Department.

This is a governance example only. It does not activate providers.

## 1) Activation review input artifacts
Use these artifacts as required input:
- `docs/management_readiness_checklist.md`
- `docs/model_governance_policy.md`
- `docs/action_department_activation_decision_format.md`
- `docs/examples/action_department_activation_decision_example.json`
- `docs/action_department_activation_approval_record_format.md`
- `docs/examples/action_department_activation_approval_record_example.json`
- `docs/examples/management_review_flow_example.md`
- `docs/management_department_prompt.md`

## 2) Review order
1. Confirm readiness gate status in `management_readiness_checklist`.
2. Confirm model/provider boundaries in `model_governance_policy`.
3. Validate activation decision payload against activation decision format.
4. Review remaining blockers and approval checkpoints.
5. Record final management outcome (`GO` / `PAUSE` / `REVIEW`) with rationale.

## 3) Human approval checkpoints
Before any activation is considered:
- Management Department reviewer must be explicitly assigned.
- Human/management checkpoint for "limited_live_provider_use_activation" must be approved.
- Approval scope and stop owner must be recorded.

## 4) Mandatory stop / REVIEW cases
Return `REVIEW` and stop when any applies:
- hard gate trigger exists for intended activation scope
- blockers are non-empty and unresolved
- latest-alias outputs are being treated as approval authority
- rollback/disable expectation is missing
- activation artifacts are missing or stale

## 5) Activation decision outcome
Possible outcomes:
- `GO`: limited activation may be considered in bounded scope only.
- `PAUSE`: prerequisites are close but unresolved.
- `REVIEW`: governance risk or ambiguity requires escalation.

Note:
- activation decision is a management governance record, not execution itself.

## 6) Autonomous continuation status
Activation approval must remain separate from autonomous continuation eligibility.

Even with activation decision `GO`:
- autonomous continuation remains `not_approved` unless separately reviewed and approved
- cheap action-model suggestions remain advisory-only for risky work

## 7) Post-decision expectations and rollback/disable stance
If any guardrail fails after activation decision:
- immediately disable limited live provider use
- route work to `REVIEW`
- document escalation reason and follow-up constraints

Until broader live-use criteria are approved:
- keep provider usage bounded to documented limited scope
- keep governance-sensitive work under management-led review
