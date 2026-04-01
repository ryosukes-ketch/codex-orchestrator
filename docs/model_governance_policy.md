# Model Governance Policy

## Purpose
Define model usage boundaries for continuation work so latest aliases are never treated as final governance authority.

## Core policy
- Hard-gate checks come before any model judgment.
- Latest aliases may assist with low-risk support tasks.
- Latest aliases must not self-authorize risky continuation.
- Final non-trivial governance decisions belong to Management Department.

## Latest alias usage rules

### `gemini-flash-lite-latest`
Allowed:
- extraction, classification, summarization, draft generation for low-risk tasks
- candidate generation for docs/test ideas
- non-authoritative triage support

Prohibited:
- final `GO` decision for medium/high-risk tasks
- approval/auth/policy/audit/schema/security decisions
- architecture reinterpretation or roadmap-phase change decisions
- irreversible implementation approval

### `gemini-flash-latest`
Allowed:
- broader low-cost support than lite variant (draft analysis, proposal structuring)
- first-pass risk hints before stronger review
- non-authoritative synthesis for management review packets

Prohibited:
- overriding hard-gate triggers
- authorizing continuation after auth/approval/policy/audit risk detection
- replacing Management Department decision on `GO` / `PAUSE` / `REVIEW`
- direct authority for production-affecting changes

## When pinned or stronger oversight is required
Use pinned or stronger oversight path (Management + Audit/Review) when:
- any hard gate is triggered
- cross-department routing ambiguity exists
- dependency/schema/security boundary is affected
- task requires final governance decision
- previous verification failed without clear local fix

## Decision authority model
- Action Department / latest aliases: advisory only.
- Progress Control Department: applies hard gates and routes decisions.
- Management Department: final authority for non-trivial continuation.

## Operational rule
If latest alias output conflicts with hard-gate or policy rules:
- discard the risky continuation suggestion
- return `REVIEW`
- escalate with explicit reason

## Pre-live guard for Action Department provider use

### 1) Allowed pre-live uses for Action Department models
Before live provider integration, Action Department models are limited to:
- extraction/classification/summarization for low-risk tasks
- candidate generation for docs/tests/local validation plans
- draft research notes and triage hints for Progress Control review

Decision meaning must stay separated:
- suggestion: raw model idea
- recommendation: structured non-final proposal for review artifacts
- approval: Management Department governance decision
- autonomous continuation eligibility: separate gate after hard-gate and review checks

### 2) Prohibited uses for latest-alias models
`gemini-flash-lite-latest` and `gemini-flash-latest` must not:
- issue final `GO` for governance-sensitive or risky work
- override hard-gate triggers
- authorize auth/approval/policy/audit/schema/security changes
- self-authorize external sends, production-impacting actions, or irreversible execution

### 3) Mandatory escalation cases
Escalate to `REVIEW` immediately when:
- any hard gate is triggered
- scope is cross-department and ownership is ambiguous
- latest-alias output conflicts with policy, direction guard, or roadmap phase
- verification status is unclear for a non-trivial change

Management Department review is mandatory for all non-trivial governance decisions.

### 4) Required artifact handoff before stronger review
Before stronger review, provide:
- management review packet (`ManagementReviewPacket`-compatible)
- review queue item (`ReviewQueueItem`-compatible)
- management decision record (`ManagementDecisionRecord`-compatible after review)

These handoff artifacts are required for auditability and must preserve hard-gate context.

### 5) Mock/stub-only boundaries before live integration
Until explicitly approved:
- provider operations remain mock/stub-first
- dry-run management flows remain simulation-only
- latest-alias outputs remain advisory-only inputs, not control-plane authority

### 6) Conditions before enabling limited live provider use
Limited live provider use may be considered only when all are true:
- pre-operation readiness gate is satisfied (`docs/management_readiness_checklist.md`)
- Management Department approval boundaries are documented and active
- hard-gate-first routing remains enforced by Progress Control
- rollback/escalation path is explicitly defined for live incidents
- no rule in this policy is weakened
