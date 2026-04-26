import json
from typing import Any

from app.llm.base import LLMClient


class MockLLMClient(LLMClient):
    """Returns deterministic mock JSON. Used when no real provider is configured."""

    def __init__(self, fixed_response: str | None = None) -> None:
        self._fixed = fixed_response
        self._last_call_metadata: dict[str, Any] = {}

    @staticmethod
    def _schema_aware_response(system: str, user: str) -> dict[str, Any]:
        system_lower = (system or "").lower()

        research_signature = (
            "summary (string), risks (list of strings), assumptions (list of strings), "
            "research_areas"
        )
        if research_signature in system_lower:
            return {
                "summary": "Mock research summary",
                "risks": ["Mock risk"],
                "assumptions": ["Mock assumption"],
                "research_areas": ["Mock area"],
            }

        design_signature = (
            "architecture (string), components (list of strings), constraints (list of strings), "
            "technical_decisions"
        )
        if design_signature in system_lower:
            return {
                "architecture": "Mock layered architecture",
                "components": ["api", "orchestrator"],
                "constraints": ["deterministic", "offline-first"],
                "technical_decisions": ["strict schemas"],
            }

        coder_signature = (
            "implementation_steps (list of strings), estimated_effort (string), corrections"
        )
        if coder_signature in system_lower:
            return {
                "status": "mock build plan",
                "scope": "mock scope",
                "implementation_steps": ["Define contracts", "Implement handlers"],
                "estimated_effort": "1d",
                "corrections": [],
            }

        tester_signature = (
            "implementation_steps (list of strings), estimated_effort (string), "
            "risks (list of strings), test_strategy"
        )
        if tester_signature in system_lower:
            return {
                "status": "mock test-ready plan",
                "scope": "mock scope",
                "implementation_steps": ["Implement", "Validate"],
                "estimated_effort": "1d",
                "risks": ["Mock integration risk"],
                "test_strategy": ["unit", "integration"],
            }

        if "verdict (string: 'approved' or 'changes_requested')" in system_lower:
            findings: list[str] = []
            if "no artifacts produced for review" in (user or "").lower():
                findings = ["No artifacts produced for review."]
            verdict = "changes_requested" if findings else "approved"
            return {
                "verdict": verdict,
                "findings": findings,
                "summary": "Mock review summary",
                "challenged_findings": [],
            }

        return {"result": "mock", "system_hint": (system or "")[:60]}

    def complete(self, system: str, user: str) -> str:  # noqa: ARG002
        if self._fixed is not None:
            self._last_call_metadata = {
                "response_mode": "fixed",
                "provider": "mock",
                "model": "mock",
            }
            return self._fixed
        self._last_call_metadata = {
            "response_mode": "schema_aware_default",
            "provider": "mock",
            "model": "mock",
        }
        return json.dumps(self._schema_aware_response(system, user))

    def pop_last_call_metadata(self) -> dict[str, Any]:
        snapshot = dict(self._last_call_metadata)
        self._last_call_metadata = {}
        return snapshot
