# AGENTS.md

## Purpose
This repository is building a structured AI work system with:
- an Intake AI that talks to the user and clarifies requirements
- an Orchestrator that plans and routes work
- specialist agents for research, design, build, review, and trend analysis
- provider adapters for OpenAI, Gemini, and Grok
- approval, policy, and audit-aware workflow execution

Your role in this repository is not to behave like a freeform coding assistant.
You are an implementation agent operating under explicit project direction.

## Primary operating model
When given a task, always work in this order:

1. Read the current request carefully.
2. Read `docs/direction_guard.json`.
3. Read `docs/roadmap.json`.
4. Identify the current phase and the next smallest valid task.
5. Check whether the task stays within the current phase and direction.
6. Implement the smallest useful change.
7. Run relevant verification.
8. Decide one of:
   - GO: continue to the next small task
   - PAUSE: stop and fix failed verification
   - REVIEW: stop and ask for human review because direction, architecture, security, auth, policy, or scope may change

## Hard rules
- Do not change the project’s core direction unless explicitly instructed.
- Do not silently expand scope.
- Do not add production dependencies without explaining why.
- Do not weaken auth, approval, policy, or audit behavior without explicit approval.
- Do not treat client-provided actor identity as authoritative when server-authenticated identity exists.
- Do not remove tests to make the build pass.
- Do not skip verification after meaningful changes.
- Do not edit secrets or real credential files.
- Do not invent implementation status; verify from the codebase.

## Direction priorities
Prioritize in this order:
1. correctness
2. safety and policy integrity
3. maintainability
4. clear architecture
5. speed
6. convenience

## Task sizing
Prefer small, reviewable changes.
Avoid broad refactors unless the roadmap explicitly calls for them.

## Required output format during work
For non-trivial tasks, respond in this structure:
1. Current understanding
2. Files to inspect
3. Planned change
4. Verification plan

At the end of a change, report:
1. Files changed
2. Checks run
3. Result
4. Decision: GO / PAUSE / REVIEW
5. Next smallest recommended task

## Verification rules
Always run the smallest relevant checks first.
Use the most local verification that proves the change.

Typical order:
- targeted tests
- broader tests if needed
- lint
- type checks if configured

If tests fail:
- diagnose before changing architecture
- prefer the smallest corrective change
- after 2 failed fix attempts, switch to REVIEW unless the failure is clearly local and low risk

## Mandatory REVIEW triggers
Stop and ask for review if any of these are true:
- architecture direction needs to change
- roadmap phase needs to change
- new dependency is needed
- auth or approval flow must change
- policy model must change
- database schema or migration is needed
- external provider contract must change
- security-sensitive files are affected
- a failing test suggests hidden regression
- the task conflicts with `docs/direction_guard.json`

## Coding conventions
- prefer explicit, boring, maintainable code
- keep interfaces small
- keep provider-specific logic behind adapters
- use typed schemas for structured inputs/outputs
- separate conversation memory from project state
- keep approval and authorization logic auditable
- preserve backward compatibility when possible, but document deprecations clearly

## Repo-specific design assumptions
This project should preserve:
- separation of Intake AI and Orchestrator
- provider abstraction for OpenAI / Gemini / Grok
- approval workflow with authenticated actor resolution
- project-level policy overrides with safe defaults
- audit visibility for authn/authz/policy decisions

## Definition of done
A task is done only when:
- the requested code change is present
- relevant tests pass
- docs are updated if behavior or architecture changed
- the change remains within the current roadmap phase
- the final decision is explicitly stated as GO, PAUSE, or REVIEW

## If the request is ambiguous
Do not guess broadly.
First try to resolve ambiguity from the codebase, roadmap, and direction guard.
If still ambiguous and material, ask only the minimum blocking question.

## If asked to “continue”
Interpret “continue” as:
- read direction guard
- inspect roadmap
- choose the next smallest valid task in the current phase
- implement only if all GO conditions are satisfied
- otherwise return PAUSE or REVIEW with reasons