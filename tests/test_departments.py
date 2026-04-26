"""Tests for department agents.

Covers:
- Fallback (no LLM) behaviour for all agents
- LLM-injected behaviour (MockLLMClient)
- Pipeline behaviour for ResearchAgent (ScopeFraming → EvidenceDraft → RiskChallenge)
- Pipeline behaviour for DesignAgent (ArchitectureDraft → ConstraintCheck → DecisionFinalizer)
- Pipeline behaviour for BuildAgent (Architect → Coder → Tester)
- Pipeline behaviour for ReviewAgent (InitialReview → CounterCheck → FinalJudgment)
- Fallback on invalid / non-JSON LLM response
- TrendAgent (unchanged interface)
"""

import json

from app.agents.departments import BuildAgent, DesignAgent, ResearchAgent, ReviewAgent, TrendAgent
from app.llm.mock_client import MockLLMClient
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


def _make_llm(response: dict) -> MockLLMClient:
    return MockLLMClient(fixed_response=json.dumps(response))


# ── fallback behaviour (no LLM injected) ─────────────────────────────────────


def test_research_agent_fallback_builds_expected_artifact() -> None:
    task = Task(id="task-research", title="Research", department=Department.RESEARCH)
    artifact = ResearchAgent().run(task, _brief())

    assert artifact.id == "artifact-task-research"
    assert artifact.task_id == "task-research"
    assert artifact.artifact_type == "research_notes"
    assert artifact.content["summary"].endswith("Build deterministic scaffold")
    assert "Requirements ambiguity" in artifact.content["risks"]


def test_design_agent_fallback_preserves_constraints() -> None:
    task = Task(id="task-design", title="Design", department=Department.DESIGN)
    artifact = DesignAgent().run(task, _brief())

    assert artifact.id == "artifact-task-design"
    assert artifact.artifact_type == "design_outline"
    assert artifact.content["constraints"] == ["python", "fastapi"]


def test_build_agent_fallback_preserves_scope() -> None:
    task = Task(id="task-build", title="Build", department=Department.BUILD)
    artifact = BuildAgent().run(task, _brief())

    assert artifact.id == "artifact-task-build"
    assert artifact.artifact_type == "build_report"
    assert artifact.content["scope"] == "backend only"


def test_review_agent_fallback_changes_requested_without_artifacts() -> None:
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    review = ReviewAgent().run(task, [])

    assert review.id == "review-task-review"
    assert review.verdict == "changes_requested"
    assert review.findings == ["No artifacts produced for review."]


def test_review_agent_fallback_approved_with_artifacts() -> None:
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

    assert review.verdict == "approved"
    assert review.findings == []


# ── LLM-aware behaviour (MockLLMClient injected) ─────────────────────────────


def test_research_agent_uses_llm_response() -> None:
    llm = _make_llm({
        "summary": "LLM summary",
        "risks": ["LLM risk"],
        "assumptions": ["assume X"],
        "research_areas": ["area A"],
    })
    task = Task(id="task-research", title="Research", department=Department.RESEARCH)
    artifact = ResearchAgent(llm=llm).run(task, _brief())

    assert artifact.artifact_type == "research_notes"
    assert artifact.content["summary"] == "LLM summary"
    assert artifact.content["risks"] == ["LLM risk"]


def test_design_agent_uses_llm_response() -> None:
    llm = _make_llm({
        "architecture": "LLM arch",
        "components": ["comp1"],
        "constraints": ["no SQL"],
        "technical_decisions": ["use REST"],
    })
    task = Task(id="task-design", title="Design", department=Department.DESIGN)
    artifact = DesignAgent(llm=llm).run(task, _brief())

    assert artifact.artifact_type == "design_outline"
    assert artifact.content["architecture"] == "LLM arch"
    assert artifact.content["components"] == ["comp1"]


def test_research_agent_exposes_internal_stage_trace() -> None:
    llm = _make_llm(
        {
            "summary": "trace summary",
            "risks": ["risk"],
            "assumptions": ["assumption"],
            "research_areas": ["area"],
        }
    )
    task = Task(id="task-research", title="Research", department=Department.RESEARCH)
    agent = ResearchAgent(llm=llm)
    _ = agent.run(task, _brief())
    trace = agent.drain_stage_trace()

    assert [entry["stage_name"] for entry in trace] == [
        "ScopeFraming",
        "EvidenceDraft",
        "RiskChallenge",
    ]
    assert [entry["sequence"] for entry in trace] == [1, 2, 3]


def test_design_agent_exposes_internal_stage_trace() -> None:
    llm = _make_llm(
        {
            "architecture": "trace arch",
            "components": ["api"],
            "constraints": ["python"],
            "technical_decisions": ["rest"],
        }
    )
    task = Task(id="task-design", title="Design", department=Department.DESIGN)
    agent = DesignAgent(llm=llm)
    _ = agent.run(task, _brief())
    trace = agent.drain_stage_trace()

    assert [entry["stage_name"] for entry in trace] == [
        "ArchitectureDraft",
        "ConstraintCheck",
        "DecisionFinalizer",
    ]
    assert [entry["sequence"] for entry in trace] == [1, 2, 3]


def test_research_agent_falls_back_on_invalid_json() -> None:
    llm = MockLLMClient(fixed_response="not valid json {{")
    task = Task(id="task-research", title="Research", department=Department.RESEARCH)
    agent = ResearchAgent(llm=llm)
    artifact = agent.run(task, _brief())
    trace = agent.drain_stage_trace()

    assert artifact.artifact_type == "research_notes"
    assert "summary" in artifact.content
    assert len(trace) == 3
    assert all(entry["success"] is False for entry in trace)
    assert all(entry["failure_reason"] == "non_json_response" for entry in trace)


def test_research_agent_records_upstream_rejection_failure_reason() -> None:
    rejection_text = (
        "LLM request rejected: Your credit balance is too low to access "
        "the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."
    )

    class _RejectionLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            self._last_call_metadata = {
                "gateway_endpoint": "chat/completions",
                "gateway_status_code": 200,
                "gateway_fallback_used": False,
                "gateway_error_kind": "upstream_rejection",
                "gateway_content_kind": "upstream_rejection",
                "gateway_upstream_rejection": True,
                "gateway_upstream_provider": "anthropic",
                "gateway_upstream_rejection_reason": "credit_balance_too_low",
                "response_mode": "plain_text_upstream_rejection",
            }
            return rejection_text

    task = Task(id="task-research", title="Research", department=Department.RESEARCH)
    agent = ResearchAgent(llm=_RejectionLLM())
    artifact = agent.run(task, _brief())
    trace = agent.drain_stage_trace()

    assert artifact.artifact_type == "research_notes"
    assert len(trace) == 3
    assert all(
        entry["failure_reason"] == "upstream_rejection:anthropic:credit_balance_too_low"
        for entry in trace
    )


# ── BuildAgent pipeline (Architect → Coder → Tester) ─────────────────────────


def test_build_agent_pipeline_uses_tester_output() -> None:
    """MockLLMClient returns the same dict for every call (all 3 stages)."""
    llm = _make_llm({
        "status": "pipeline complete",
        "scope": "backend",
        "implementation_steps": ["step 1", "step 2"],
        "estimated_effort": "3 days",
        "risks": ["risk A"],
        "architecture": "layered",
        "components": ["api", "db"],
        "test_strategy": ["unit tests", "integration tests"],
        "corrections": [],
    })
    task = Task(id="task-build", title="Build", department=Department.BUILD)
    artifact = BuildAgent(llm=llm).run(task, _brief())

    assert artifact.artifact_type == "build_report"
    # Should come from Tester (last stage) — since mock returns same JSON every time
    assert artifact.content["implementation_steps"] == ["step 1", "step 2"]
    assert artifact.content["risks"] == ["risk A"]
    assert artifact.content["test_strategy"] == ["unit tests", "integration tests"]


def test_build_agent_pipeline_falls_back_on_all_stage_failures() -> None:
    """If the LLM always returns non-JSON, the pipeline falls back to deterministic output."""
    llm = MockLLMClient(fixed_response="definitely not json")
    task = Task(id="task-build", title="Build", department=Department.BUILD)
    artifact = BuildAgent(llm=llm).run(task, _brief())

    assert artifact.artifact_type == "build_report"
    assert artifact.content["scope"] == "backend only"  # fallback value
    assert artifact.content["implementation_steps"] == []


def test_build_agent_pipeline_partial_stage_failure() -> None:
    """If only some stages produce valid JSON, the last successful one wins."""
    responses = iter([
        # Architect succeeds
        json.dumps({
            "architecture": "clean arch",
            "components": ["svc", "repo"],
            "interfaces": [],
            "risks": [],
        }),
        # Coder fails
        "not json",
        # Tester succeeds — but only returns tester fields
        json.dumps({
            "status": "tested",
            "scope": "full stack",
            "implementation_steps": ["impl 1"],
            "estimated_effort": "2 days",
            "risks": ["dep risk"],
            "test_strategy": ["smoke test"],
        }),
    ])

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            return next(responses)

    task = Task(id="task-build", title="Build", department=Department.BUILD)
    artifact = BuildAgent(llm=_SeqLLM()).run(task, _brief())

    assert artifact.artifact_type == "build_report"
    assert artifact.content["status"] == "tested"
    assert artifact.content["risks"] == ["dep risk"]


# ── ReviewAgent pipeline (InitialReview → CounterCheck → FinalJudgment) ──────


def test_review_agent_pipeline_uses_final_verdict() -> None:
    """Final stage verdict should win."""
    llm = _make_llm({
        "verdict": "approved",
        "findings": [],
        "summary": "All good",
        "challenged_findings": [],
    })
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    artifacts = [
        Artifact(
            id="a1", task_id="task-build", artifact_type="build_report",
            content={"status": "ok"},
        )
    ]
    review = ReviewAgent(llm=llm).run(task, artifacts)

    assert review.verdict == "approved"
    assert review.findings == []


def test_review_agent_pipeline_changes_requested() -> None:
    llm = _make_llm({
        "verdict": "changes_requested",
        "findings": ["Missing tests", "No docs"],
        "summary": "Needs work",
        "challenged_findings": [],
    })
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    artifacts = [
        Artifact(
            id="a1", task_id="task-build", artifact_type="build_report",
            content={"status": "partial"},
        )
    ]
    review = ReviewAgent(llm=llm).run(task, artifacts)

    assert review.verdict == "changes_requested"
    assert "Missing tests" in review.findings


def test_review_agent_pipeline_includes_brief_context() -> None:
    class _CaptureLLM(MockLLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, str]] = []

        def complete(self, system: str, user: str) -> str:
            self.calls.append((system, user))
            return json.dumps(
                {
                    "verdict": "approved",
                    "findings": [],
                    "summary": "Aligned with brief",
                    "challenged_findings": [],
                }
            )

    llm = _CaptureLLM()
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    artifacts = [
        Artifact(
            id="a1",
            task_id="task-build",
            artifact_type="build_report",
            content={"status": "partial"},
        )
    ]

    review = ReviewAgent(llm=llm).run(task, artifacts, brief=_brief())

    assert review.verdict == "approved"
    assert llm.calls
    prompt = llm.calls[0][1]
    assert "Build deterministic scaffold" in prompt
    assert "tests pass" in prompt
    assert "\"artifacts\"" in prompt


def test_review_agent_pipeline_falls_back_on_all_stage_failures() -> None:
    llm = MockLLMClient(fixed_response="not json at all")
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    artifacts = [
        Artifact(id="a1", task_id="t1", artifact_type="build_report", content={"status": "ok"})
    ]
    review = ReviewAgent(llm=llm).run(task, artifacts)

    # Fallback with artifacts → approved
    assert review.verdict == "approved"
    assert review.findings == []


def test_review_agent_pipeline_invalid_verdict_normalised_to_approved() -> None:
    """An unrecognised verdict string should be normalised to 'approved'."""
    llm = _make_llm({
        "verdict": "maybe",
        "findings": [],
        "summary": "uncertain",
    })
    task = Task(id="task-review", title="Review", department=Department.REVIEW)
    artifacts = [
        Artifact(id="a1", task_id="t1", artifact_type="build_report", content={"status": "ok"})
    ]
    review = ReviewAgent(llm=llm).run(task, artifacts)

    assert review.verdict == "approved"


# ── TrendAgent (unchanged interface) ────────────────────────────────────────


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
    assert artifact.artifact_type == "trend_analysis"
    assert artifact.content["provider"] == "fake"
