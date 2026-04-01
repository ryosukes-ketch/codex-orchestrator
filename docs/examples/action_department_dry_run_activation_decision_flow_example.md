# Action Department Dry-Run Activation Decision Flow Example

## Purpose
Show a dry-run decision sequence for limited live provider activation in Action Department.

This flow is repository-side governance simulation only.
It does not trigger live provider activation.

## Flow sequence
1. Load activation decision input:
   - `docs/examples/action_department_activation_decision_example.json`
2. Run management review and human checkpoint verification:
   - check readiness gate in `docs/management_readiness_checklist.md`
   - confirm checkpoint `limited_live_provider_use_activation`
3. Record manual activation approval outcome:
   - `docs/examples/action_department_activation_approval_record_example.json`
   - lifecycle variants:
     - `docs/examples/action_department_activation_approval_record_pause_example.json`
     - `docs/examples/action_department_activation_approval_record_review_example.json`
4. Confirm recommendation outcome (`GO` / `PAUSE` / `REVIEW`) and retained constraints.
5. Confirm autonomous continuation status remains separately controlled.

## Governance boundary (explicit)
- Activation approval does not by itself grant autonomous continuation.
- Even when recommendation is `GO`, autonomous continuation can remain `not_approved`.
- Cheap/latest-alias Action Department outputs are advisory-only for risky work.
- Shared boundary wording source: `docs/action_department_activation_decision_format.md` (Shared governance boundary).

## Mandatory stop conditions in dry-run
Return/retain `REVIEW` and stop activation progression when:
- hard-gate concerns are unresolved
- blockers remain non-empty
- rollback/disable expectation is missing
- ownership or escalation destination is ambiguous

## Output expectation
A valid dry-run flow produces:
- one activation decision input artifact
- one management/human-reviewed activation approval record outcome
- explicit autonomous continuation status
- explicit rollback/disable expectation
