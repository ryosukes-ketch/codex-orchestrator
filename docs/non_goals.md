# Non-Goals

## System-level non-goals
- Not a direct live-execution control plane for autonomous production actions.
- Not a replacement for human review in governance-sensitive paths.
- Not a schema-redesign or architecture-redesign vehicle in current phase.

## Offline-validation non-goals
- No proof of real provider behavior under production traffic.
- No proof of JWT/OIDC production auth integration correctness.
- No proof of production database migration/rollback execution.
- No proof of production SLO compliance under live load.

## Implementation non-goals for this phase
- No broad feature expansion unrelated to deterministic dry-run requirements.
- No hidden-state orchestration that bypasses explicit artifact handoff.
- No silent unknown-value fallback in mapping chains where KeyError is expected.

## When live validation is mandatory
- Real credentials and network/provider behavior are involved.
- Real auth issuer/claim behavior must be verified.
- Real persistence safety, durability, and rollback behavior must be verified.
