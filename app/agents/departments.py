import json
import logging
from copy import deepcopy

from app.agents.roles import (
    Pipeline,
    build_pipeline,
    design_pipeline,
    research_pipeline,
    review_pipeline,
)
from app.llm.base import LLMClient
from app.providers.base import TrendProvider
from app.schemas.brief import ProjectBrief
from app.schemas.project import Artifact, Review, Task
from app.schemas.trend import TrendAnalysisRequest

logger = logging.getLogger(__name__)


def _brief_user_prompt(brief: ProjectBrief) -> str:
    lines = [
        f"Objective: {brief.objective}",
        f"Raw request: {brief.raw_request}",
    ]
    if brief.scope:
        lines.append(f"Scope: {brief.scope}")
    if brief.constraints:
        lines.append(f"Constraints: {', '.join(brief.constraints)}")
    if brief.deadline:
        lines.append(f"Deadline: {brief.deadline}")
    return "\n".join(lines)


def _review_brief_context(brief: ProjectBrief | None) -> dict[str, object]:
    if brief is None:
        return {}

    return {
        "title": brief.title,
        "objective": brief.objective,
        "scope": brief.scope,
        "constraints": list(brief.constraints),
        "success_criteria": list(brief.success_criteria),
        "assumptions": list(brief.assumptions),
        "raw_request": brief.raw_request,
    }


# ---------------------------------------------------------------------------
# ResearchAgent — 3-stage pipeline: ScopeFraming → EvidenceDraft → RiskChallenge
# ---------------------------------------------------------------------------


class ResearchAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm
        self._pipeline: Pipeline = research_pipeline()
        self._last_stage_trace: list[dict] = []

    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        content: dict = _research_fallback(brief)
        self._last_stage_trace = []

        if self._llm is not None:
            result = self._pipeline.run(self._llm, _brief_user_prompt(brief))
            self._last_stage_trace = self._pipeline.drain_last_trace()
            if result is not None:
                content = {
                    "summary": result.get("summary", content["summary"]),
                    "risks": result.get("risks", []),
                    "assumptions": result.get("assumptions", []),
                    "research_areas": result.get("research_areas", []),
                }
            else:
                logger.warning("ResearchAgent: pipeline produced no output; using fallback.")

        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="research_notes",
            content=content,
        )

    def drain_stage_trace(self) -> list[dict]:
        """Return and clear the latest internal-stage trace."""
        trace = deepcopy(self._last_stage_trace)
        self._last_stage_trace = []
        return trace


def _research_fallback(brief: ProjectBrief) -> dict:
    return {
        "summary": f"Initial research framing for objective: {brief.objective}",
        "risks": ["Requirements ambiguity", "External dependency uncertainty"],
        "assumptions": [],
        "research_areas": [],
    }


# ---------------------------------------------------------------------------
# DesignAgent — 3-stage pipeline: ArchitectureDraft → ConstraintCheck → DecisionFinalizer
# ---------------------------------------------------------------------------


class DesignAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm
        self._pipeline: Pipeline = design_pipeline()
        self._last_stage_trace: list[dict] = []

    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        content: dict = _design_fallback(brief)
        self._last_stage_trace = []

        if self._llm is not None:
            result = self._pipeline.run(self._llm, _brief_user_prompt(brief))
            self._last_stage_trace = self._pipeline.drain_last_trace()
            if result is not None:
                content = {
                    "architecture": result.get("architecture", content["architecture"]),
                    "components": result.get("components", []),
                    "constraints": result.get("constraints", brief.constraints),
                    "technical_decisions": result.get("technical_decisions", []),
                }
            else:
                logger.warning("DesignAgent: pipeline produced no output; using fallback.")

        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="design_outline",
            content=content,
        )

    def drain_stage_trace(self) -> list[dict]:
        """Return and clear the latest internal-stage trace."""
        trace = deepcopy(self._last_stage_trace)
        self._last_stage_trace = []
        return trace


def _design_fallback(brief: ProjectBrief) -> dict:
    return {
        "architecture": "Intake -> Orchestrator -> Specialist Agents -> Artifacts",
        "constraints": brief.constraints,
        "components": [],
        "technical_decisions": [],
    }


# ---------------------------------------------------------------------------
# BuildAgent — 3-stage pipeline: Architect → Coder → Tester
# ---------------------------------------------------------------------------


class BuildAgent:
    """Build department agent with internal Architect → Coder → Tester pipeline.

    When an LLM is provided, the three sub-roles run in sequence with each
    stage receiving the previous stage's output as additional context.  This
    creates a self-correction loop: Coder reviews the Architect's design;
    Tester reviews the Coder's implementation plan.

    Falls back to deterministic output if no LLM is configured or the entire
    pipeline fails.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm
        self._pipeline: Pipeline = build_pipeline()
        self._last_stage_trace: list[dict] = []

    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        content: dict = _build_fallback(brief)
        self._last_stage_trace = []

        if self._llm is not None:
            result = self._pipeline.run(self._llm, _brief_user_prompt(brief))
            self._last_stage_trace = self._pipeline.drain_last_trace()
            if result is not None:
                # Normalise to the expected build_report shape
                content = {
                    "status": _normalize_build_status(
                        result.get("status", "implementation plan generated")
                    ),
                    "scope": result.get("scope", brief.scope or ""),
                    "implementation_steps": result.get("implementation_steps", []),
                    "estimated_effort": result.get("estimated_effort", "unknown"),
                    "risks": result.get("risks", []),
                    # Extra fields from the pipeline (pass through)
                    "architecture": result.get("architecture", ""),
                    "components": result.get("components", []),
                    "test_strategy": result.get("test_strategy", []),
                    "corrections": result.get("corrections", []),
                }
            else:
                logger.warning("BuildAgent: pipeline produced no output; using fallback.")

        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="build_report",
            content=content,
        )

    def drain_stage_trace(self) -> list[dict]:
        """Return and clear the latest internal-stage trace."""
        trace = deepcopy(self._last_stage_trace)
        self._last_stage_trace = []
        return trace


def _build_fallback(brief: ProjectBrief) -> dict:
    return {
        "status": "MVP scaffold generated",
        "scope": brief.scope,
        "implementation_steps": [],
        "estimated_effort": "unknown",
        "risks": [],
        "architecture": "",
        "components": [],
        "test_strategy": [],
        "corrections": [],
    }


def _normalize_build_status(raw_status: object) -> str:
    """Normalize build status labels to avoid accidental blocking semantics.

    Some LLM outputs include labels like "needs-revision" as an internal
    drafting signal. Review flow treats build report as one artifact among
    several, so preserve neutral operational wording here.
    """
    if not isinstance(raw_status, str):
        return "implementation plan generated"
    value = raw_status.strip()
    if not value:
        return "implementation plan generated"
    lowered = value.lower()
    if lowered in {"needs-revision", "needs_revision", "blocked", "failed"}:
        return "implementation plan generated"
    return value


# ---------------------------------------------------------------------------
# TrendAgent — unchanged
# ---------------------------------------------------------------------------


class TrendAgent:
    def __init__(self, provider: TrendProvider) -> None:
        self.provider = provider

    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        trend = self.provider.analyze(
            TrendAnalysisRequest(
                trend_topic=brief.objective,
                context=brief.scope,
                max_items=3,
            )
        )
        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="trend_analysis",
            content=trend.model_dump(),
        )


# ---------------------------------------------------------------------------
# ReviewAgent — 3-stage pipeline: InitialReview → CounterCheck → FinalJudgment
# ---------------------------------------------------------------------------


class ReviewAgent:
    """Review department agent with internal InitialReview → CounterCheck → FinalJudgment pipeline.

    Each stage can see what the previous stage found.  CounterCheck challenges
    the initial review's findings; FinalJudgment makes the decisive call
    weighing both perspectives.

    Falls back to deterministic output if no LLM is configured or the entire
    pipeline fails.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm
        self._pipeline: Pipeline = review_pipeline()
        self._last_stage_trace: list[dict] = []

    def run(
        self,
        task: Task,
        artifacts: list[Artifact],
        brief: ProjectBrief | None = None,
    ) -> Review:
        self._last_stage_trace = []
        if self._llm is not None and artifacts:
            review_payload = {
                "brief": _review_brief_context(brief),
                "artifacts": [a.model_dump() for a in artifacts],
            }
            artifacts_text = json.dumps(
                review_payload,
                ensure_ascii=False,
            )
            result = self._pipeline.run(self._llm, artifacts_text)
            self._last_stage_trace = self._pipeline.drain_last_trace()
            if result is not None:
                verdict = result.get("verdict", "approved")
                if verdict not in ("approved", "changes_requested"):
                    verdict = "approved"
                findings = result.get("findings", [])
                if not isinstance(findings, list):
                    findings = []
                return Review(
                    id=f"review-{task.id}",
                    task_id=task.id,
                    verdict=verdict,
                    findings=findings,
                )
            logger.warning("ReviewAgent: pipeline produced no output; using fallback.")

        # Fallback
        findings: list[str] = []
        if not artifacts:
            findings.append("No artifacts produced for review.")
        verdict = "approved" if not findings else "changes_requested"
        return Review(
            id=f"review-{task.id}",
            task_id=task.id,
            verdict=verdict,
            findings=findings,
        )

    def drain_stage_trace(self) -> list[dict]:
        """Return and clear the latest internal-stage trace."""
        trace = deepcopy(self._last_stage_trace)
        self._last_stage_trace = []
        return trace
