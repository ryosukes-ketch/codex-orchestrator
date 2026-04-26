# Self-Serve Onboarding Guardrails

## Purpose
Provide deterministic onboarding checks before first live run.

## Guardrail checklist
- [ ] `.env` exists and required keys are present (`STATE_BACKEND`, `STATE_BACKEND_STRICT`, `SQLITE_DB_PATH`)
- [ ] `STATE_BACKEND=sqlite` for local self-serve baseline
- [ ] `STATE_BACKEND_STRICT=true` for fail-fast behavior
- [ ] `OPERATOR_API_TIMEOUT_SECONDS` set for live OpenClaw profiles (recommend 600)
- [ ] OpenClaw gateway check passes when openclaw models are configured

## Preflight commands
```powershell
.\scripts\self-serve-preflight.ps1 -EnvPath .\.env
.\scripts\preflight.ps1
.\scripts\sqlite-verify.ps1
.\scripts\openclaw-gateway-check.ps1 -AgentId codex-orchestrator -BackendModel openai-codex/gpt-5.2
```

## Fail-fast policy
If any guardrail fails:
1. stop startup/readiness execution,
2. capture command output,
3. collect support bundle once a readiness/suite manifest exists.

## Linkage
- Startup: `docs/operational_startup_runbook.md`
- Readiness: `docs/operational_readiness_runbook.md`
- Support: `docs/commercial_pilot_support_runbook.md`
- Support-safe packaging: `docs/self_serve_support_safe_packaging.md`
- Handoff readiness: `docs/self_serve_commercial_handoff_readiness.md`
