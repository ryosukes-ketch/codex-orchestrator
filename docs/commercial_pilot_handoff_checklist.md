# Commercial Pilot Handoff Checklist

## Purpose
Use this checklist when handing pilot operation to another operator or customer-side owner.

## 1. Handoff package
- [ ] `docs/commercial_pilot_delivery_kit.md`
- [ ] `docs/commercial_pilot_support_runbook.md`
- [ ] `docs/commercial_pilot_scope_and_constraints.md`
- [ ] `docs/commercial_pilot_acceptance_checklist.md`
- [ ] `docs/commercial_pilot_inquiry_template.md`

## 2. Runtime and env handoff
- [ ] `.env` keys reviewed (no secrets committed)
- [ ] OpenClaw gateway token source explained
- [ ] timeout defaults explained (`OPERATOR_API_TIMEOUT_SECONDS`)

## 3. Script operation handoff
- [ ] startup command demonstrated
- [ ] readiness command demonstrated
- [ ] operator run/status/approve/reject/revise/replan/audit sequence demonstrated
- [ ] support-bundle collection demonstrated

## 4. Artifact navigation handoff
- [ ] readiness manifest navigation explained
- [ ] suite manifest navigation explained
- [ ] stage gate and audit assert location explained

## 5. Constraint acknowledgment
- [ ] customer-side owner acknowledges in-scope and out-of-scope constraints
- [ ] escalation boundary acknowledged

## 6. Final handoff record
- Handoff date/time:
- From operator:
- To operator/customer owner:
- Notes:
