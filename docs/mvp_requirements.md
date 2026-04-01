# MVP Requirements

## Scope
Minimum requirements already satisfied by the current offline deterministic implementation.

## MVP functional requirements
- MVP-01 Intake to current brief:
  - The system must convert intake text into a normalized brief/current-brief artifact.
- MVP-02 Triage and management projection:
  - The system must evaluate GO/PAUSE/REVIEW and project autonomous continuation allowance.
- MVP-03 Artifact composition:
  - The system must generate management summary, projected activation decision, and approval record.
- MVP-04 Handoff construction:
  - The system must construct handoff envelope and downstream payloads from explicit artifacts.
- MVP-05 Pure helper-chain evaluation:
  - Receiver/consumer/release derivations must be deterministic and side-effect free.
- MVP-06 Unknown mapping boundary behavior:
  - Unknown mapping values in helper chains must raise KeyError (no silent fallback).
- MVP-07 Offline reviewability:
  - Core behavior must be testable offline with deterministic outputs and stable contracts.

## MVP non-functional requirements
- Deterministic helper transformations.
- Reviewable artifacts and decision trace.
- No dependency on live provider execution for core validation.

## Validation status
- MVP requirements are offline-validated in current baseline (`pytest` and `ruff` green).
- Requirement-to-code/test traceability is maintained in `docs/requirement_traceability_matrix.md`.
