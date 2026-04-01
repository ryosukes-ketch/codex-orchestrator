from app.providers.base import TrendProvider
from app.schemas.brief import ProjectBrief
from app.schemas.project import Artifact, Review, Task
from app.schemas.trend import TrendAnalysisRequest


class ResearchAgent:
    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="research_notes",
            content={
                "summary": f"Initial research framing for objective: {brief.objective}",
                "risks": ["Requirements ambiguity", "External dependency uncertainty"],
            },
        )


class DesignAgent:
    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="design_outline",
            content={
                "architecture": "Intake -> Orchestrator -> Specialist Agents -> Artifacts",
                "constraints": brief.constraints,
            },
        )


class BuildAgent:
    def run(self, task: Task, brief: ProjectBrief) -> Artifact:
        return Artifact(
            id=f"artifact-{task.id}",
            task_id=task.id,
            artifact_type="build_report",
            content={
                "status": "MVP scaffold generated",
                "scope": brief.scope,
            },
        )


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


class ReviewAgent:
    def run(self, task: Task, artifacts: list[Artifact]) -> Review:
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

