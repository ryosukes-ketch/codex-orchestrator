# Runtime and Storage Boundary

## Purpose
Prevent product-mix confusion by declaring the runtime and persistence boundary
between AI Work System and MacroPulser in this shared repository.

## Runtime boundary

| Runtime | Primary entrypoint | Primary scripts |
|---|---|---|
| AI Work System | `app/ai_work_system/main.py` (or `app/api/main.py`) | `scripts/ai_work_system/*`, `scripts/operator-*.ps1`, `scripts/release-readiness.ps1` |
| MacroPulser | `app/macro_pulser/main.py` | `scripts/macro_pulser/*` |

Legacy aliases are compatibility shims only:
- `app/main.py` (MacroPulser compatibility)
- root wrapper scripts that forward to split paths

## Persistence boundary

| Runtime | Persistence module | Default profile |
|---|---|---|
| AI Work System | `app/state/*` | `STATE_BACKEND=sqlite` (local ops), optional memory/postgres per runbook |
| MacroPulser | `app/db/*` | PostgreSQL + Alembic workflow |

These layers are intentionally separate and should not be treated as one shared
database model.

## Operational policy
- Validate AI Work System with `scripts/ai_work_system/start-server.ps1` and readiness/operator gates.
- Validate MacroPulser with `scripts/macro_pulser/run-api.ps1` and macro smoke flows.
- Do not assume migrations in `app/db/*` apply to AI Work System state in `app/state/*`.

