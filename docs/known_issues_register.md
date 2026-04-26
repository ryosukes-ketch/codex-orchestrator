# Known Issues Register

Track launch-phase known issues with deterministic ownership and status transitions.

## Status vocabulary
- `open`
- `mitigated`
- `resolved`
- `accepted_risk`

## Register

| Issue ID | Title | Severity | Status | Owner | First Seen (UTC) | Workaround | Next Action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| KI-20260423-001 | `self-serve-update-guard.ps1` requires sqlite DB path to exist before pre-update evidence run. | P3 | mitigated | admin | 2026-04-23T00:25:00Z | For launch evidence, collect support evidence via `operator-support-bundle.ps1` -> `self-serve-support-intake.ps1` -> `self-serve-handoff-package.ps1`; run update-guard after sqlite preconditions are satisfied. | Keep documented until sqlite initialization contract is explicitly validated in launch runbooks. |
| KI-20260425-001 | Steady-state watchlist release lane remains `escalate` with `owner_assignment_required` on release evidence closeout items. | P2 | open | release_ops_owner | 2026-04-24T15:34:59Z | Keep cadence/checkpoint/watchlist cycle running and treat release lane as escalation-managed until owner acknowledgement is captured. | Execute go/hold/rollback meeting with explicit owner assignment acknowledgement; then rerun `ga-steady-state-escalation-watchlist-route.ps1` and verify watchlist delta decreases. |

| KI-STEADY-RELEASE-OWNER-PENDING | Release lane watchlist contains owner_assignment_required items in steady-state loop. | P2 | open | release_ops_owner | 2026-04-24T16:04:31.5648129Z | Maintain escalation watchlist routing and owner acknowledgment workflow. | Assign owner in release-ops meeting and rerun steady-state watchlist route. |

| KI-STEADY-REPEATED-ESCALATE | Overall checkpoint/watchlist decision remains scalate across consecutive steady-state cycles. | P2 | open | steady_state_ops_owner | 2026-04-24T16:09:05.0272385Z | Continue cadence/checkpoint/watchlist loop with bounded remediation tracking. | Reduce escalate lane count or downgrade to watch before next checkpoint refresh. |

## Update log
- 2026-04-23: Added `KI-20260423-001` from phase_11 closeout evidence run observations.
- 2026-04-25: Added `KI-20260425-001` from steady-state checkpoint/watchlist cycle where release lane remained `escalate` with `owner_assignment_required`.
- 2026-04-25: Observed owner_assignment_required_count=1 in steady-state run steady-state-run-20260425-010428.
- 2026-04-25: Observed owner_assignment_required_count=1 in steady-state run steady-state-run-20260425-010858.
- 2026-04-25: consecutive_escalate_count=2 observed in steady-state run steady-state-run-20260425-010858.
