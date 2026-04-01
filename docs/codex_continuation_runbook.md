# Codex Continuation Runbook

## Purpose
Use this runbook for repeatable Codex continuation runs under repository governance.

## When to use continuation automation
- Continue a small, phase-aligned task already scoped in this repository.
- Apply docs/test/local helper updates that do not cross hard gates.
- Execute repeated "inspect -> decide -> small change -> verify" loops.

## When to stop and require review
Stop automation and return `REVIEW` when any of these are true:
- auth, approval, policy, strict mode, actor trust, or audit semantics change
- schema/migration or dependency addition is required
- roadmap phase/direction change is required
- external provider contract or security boundary is affected

## GO / PAUSE / REVIEW interpretation
- `GO`: safe to continue with smallest phase-aligned change and local verification.
- `PAUSE`: local blocker/uncertainty exists; isolate issue before continuing.
- `REVIEW`: governance-sensitive boundary crossed; escalate to Management Department.

## Standard continuation loop
1. Read `AGENTS.md`.
2. Read `docs/direction_guard.json`.
3. Read `docs/roadmap.json`.
4. Identify active phase and next smallest task.
5. Inspect minimum relevant files.
6. Apply hard gate check.
7. Decide `GO` / `PAUSE` / `REVIEW`.
8. If `GO`, implement smallest change and run smallest relevant verification.
9. Report decision and reason explicitly.

## Skill alignment
- Primary skill: [`continue-workflow`](../.agents/skills/continue-workflow/SKILL.md)
- Keep output structure consistent with skill requirements:
  - active phase
  - candidate task
  - files inspected
  - planned change
  - verification
  - final decision

## Operational notes
- Action/cheap-model output is advisory only.
- Risky continuation cannot be self-authorized by low-cost model suggestions.
- Keep scope minimal; avoid silent reprioritization.
- For startup/deployment-like offline validation matrices, use `docs/operational_startup_runbook.md`.
