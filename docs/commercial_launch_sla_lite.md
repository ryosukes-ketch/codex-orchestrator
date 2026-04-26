# Commercial Launch SLA-Lite and Incident Classification

## Purpose
Define minimum response/recovery expectations for commercial launch readiness without introducing contractual SLA complexity.

## Scope and limits
- SLA-lite is an operational expectation baseline for launch governance decisions.
- This is not a legal SLA document.
- Applies after evidence package intake is complete.

## Severity tiers

| Tier | Definition | Typical examples |
| --- | --- | --- |
| `P1` | Critical launch-affecting incident with no acceptable workaround. | strict gate hard fail in production-like run, policy/auth boundary break, unrecoverable startup failure. |
| `P2` | Major degradation with limited workaround. | repeated provider auth instability, partial workflow failure with manual continuation path. |
| `P3` | Minor/non-blocking issue with stable workaround. | documentation mismatch, low-impact script output inconsistency. |

## Response expectations

| Tier | First response target | Mitigation target | Recovery objective guidance |
| --- | --- | --- | --- |
| `P1` | within 30 minutes | workaround or rollback recommendation within 2 hours | restore launch-critical path within same business day when feasible |
| `P2` | within 4 hours | mitigation plan within 1 business day | permanent fix or accepted-risk decision within 3 business days |
| `P3` | within 1 business day | scheduled fix decision within 3 business days | close in normal release cycle |

## Mandatory support bundle conditions
- Incidents are not triaged without:
  - `support-bundle.manifest.json`
  - `failure-classification.json`
  - source readiness/bundle manifest reference
- For `P1` and `P2`, include:
  - `support-intake.manifest.json`
  - stage gate/audit assertion output when policy/auth is involved

## Classification linkage
Use `failure-classification.json` category as first routing input:
- `runtime`
- `provider_auth`
- `policy`
- `semantic_output`
- `persistence_restore`
- `operator_flow`

Then assign severity (`P1`/`P2`/`P3`) using customer impact and workaround availability.

## Known issue handling
- If incident matches an existing known issue:
  - reference issue id in release notes
  - confirm workaround validity
  - keep severity aligned with real impact (do not auto-downgrade)
- If incident is new:
  - create a new row in `docs/known_issues_register.md`
  - set initial status to `open`

## Rollback coordination
- `P1` incidents must include explicit rollback signal review (`hold_and_investigate` / `rollback_recommended` / `rollback_required`).
- If rollback is executed, record evidence paths in staging execution record and release notes artifact.
