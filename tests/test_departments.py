from app.agents.departments import BuildAgent, DesignAgent, ResearchAgent, ReviewAgent, TrendAgent
from app.schemas.brief import ProjectBrief
from app.schemas.project import Artifact, Department, Task
from app.schemas.trend import TrendAnalysisRequest, TrendAnalysisResult, TrendCandidate


def _brief() -> ProjectBrief:
    return ProjectBrief(
        title="AI work system",
        objective="Build deterministic scaffold",
        scope="backend only",
        constraints=["python", "fastapi"],
        success_criteria=["tests pass"],
        deadline="2026-06-01",
        stakeholders=["platform"],
        assumptions=["MVP first"],
        raw_request="Build deterministic scaffold",
    )


def test_research_agent_run_builds_expected_artifact() -> None:
    task = Task(id="task-research", title="Research", department=Department.RESEARCH)
    artifact = ResearchAgent().run(task, _brief())

    assert artifact.id == "artifact-task-research"
    assert artifact.task_id == "task-research"
    assert artifact.artifact_type == "research_notes"
    assert artifact.content["summary"].endswith("Build deterministic scaffold")
    assert "Requirements ambiguity" in artifact.content["risks"]


def test_design_agent_run_preserves_constraints() -> None:
    task = Task(id="task-design", title="Design", department=Department.DESIGN)
    artifact = DesignAgent().run(task, _brief())

    assert artifact.id == "artifact-task-design"
    assert artifact.artifact_type == "design_outline"
    assert artifact.content["constraints"] == ["python", "fastapi"]


def test_build_agent_run_preserves_scope() -> None:
    task = Task(id="task-build", title="Build", department=Department.BUILD)
    artifact = BuildAgent().run(task, _brief())

    assert artifact.id == "artifact-task-build"
    assert artifact.artifact_type == "build_report"
    assert artifact.content["scope"] == "backend only"


def test_trend_agent_run_maps_brief_to_request_and_result_to_artifact() -> None:
    captured: list[TrendAnalysisRequest] = []

    class _Provider:
        def analyze(self, request: TrendAnalysisRequest) -> TrendAnalysisResult:
            captured.append(request)
            return TrendAnalysisResult(
                provider="fake",
                trend_topic=request.trend_topic,
                candidate_trends=[
                    TrendCandidate(
                        name="Deterministic tests",
                        description="Increase branch confidence",
                        freshness=0.9,
                        confidence=0.8,
                        adoption_note="Stable and reproducible.",
                    )
                ],
            )

    task = Task(id="task-trend", title="Trend", department=Department.TREND)
    artifact = TrendAgent(provider=_Provider()).run(task, _brief())

    assert len(captured) == 1
    assert captured[0].trend_topic == "Build deterministic scaffold"
    assert captured[0].context == "backend only"
    assert captured[0].max_items == 3
    assert artifact.id == "artifact-task-trend"
    assert artifact.artifact_type == "trend_analysis"
    assert artifact.content["provider"] == "fake"
    assert artifact.content["trend_topic"] == "Build deterministic scaffold"


def test_review_agent_run_changes_requested_without_artifacts() -> None:
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    review = ReviewAgent().run(task, [])

    assert review.id == "review-task-review"
    assert review.verdict == "changes_requested"
    assert review.findings == ["No artifacts produced for review."]


def test_review_agent_run_approved_with_artifacts() -> None:
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    artifacts = [
        Artifact(
            id="artifact-1",
            task_id="task-build",
            artifact_type="build_report",
            content={"status": "ok"},
        )
    ]
    review = ReviewAgent().run(task, artifacts)

    assert review.id == "review-task-review"
    assert review.verdict == "approved"
    assert review.findings == []
