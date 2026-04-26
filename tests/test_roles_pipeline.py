"""Tests for the sub-role Pipeline infrastructure (app/agents/roles.py)."""

import json

from app.agents.roles import (
    Pipeline,
    SubRole,
    _try_parse_json,
    build_pipeline,
    design_pipeline,
    research_pipeline,
    review_pipeline,
)
from app.llm.mock_client import MockLLMClient

# ── _try_parse_json ──────────────────────────────────────────────────────────


def test_try_parse_json_valid_dict() -> None:
    assert _try_parse_json('{"a": 1}') == {"a": 1}


def test_try_parse_json_invalid() -> None:
    assert _try_parse_json("not json") is None


def test_try_parse_json_list_returns_none() -> None:
    assert _try_parse_json("[1, 2, 3]") is None


def test_try_parse_json_extracts_embedded_object() -> None:
    text = 'model output:\n{"verdict":"approved","findings":[]}\nthanks'
    assert _try_parse_json(text) == {"verdict": "approved", "findings": []}


# ── SubRole ──────────────────────────────────────────────────────────────────


def test_subrole_returns_parsed_dict() -> None:
    role = SubRole(
        name="Test",
        system_prompt="you are a test bot",
        user_prompt_fn=lambda ctx, prior: ctx,
    )
    llm = MockLLMClient(fixed_response=json.dumps({"result": "ok"}))
    out = role.run(llm, "hello", [])
    assert out == {"result": "ok"}


def test_subrole_returns_none_on_non_json() -> None:
    role = SubRole(
        name="Test",
        system_prompt="sys",
        user_prompt_fn=lambda ctx, prior: ctx,
    )
    llm = MockLLMClient(fixed_response="not json")
    out = role.run(llm, "ctx", [])
    assert out is None


def test_subrole_returns_none_on_missing_required_keys() -> None:
    role = SubRole(
        name="Test",
        system_prompt="sys",
        user_prompt_fn=lambda ctx, prior: ctx,
        required_keys=["must_have"],
    )
    llm = MockLLMClient(fixed_response=json.dumps({"other": "field"}))
    out = role.run(llm, "ctx", [])
    assert out is None


def test_subrole_passes_when_required_keys_present() -> None:
    role = SubRole(
        name="Test",
        system_prompt="sys",
        user_prompt_fn=lambda ctx, prior: ctx,
        required_keys=["key_a", "key_b"],
    )
    llm = MockLLMClient(fixed_response=json.dumps({"key_a": 1, "key_b": 2}))
    out = role.run(llm, "ctx", [])
    assert out == {"key_a": 1, "key_b": 2}


def test_subrole_returns_none_on_llm_exception() -> None:
    class _ErrorLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("boom")

    role = SubRole(
        name="Test",
        system_prompt="sys",
        user_prompt_fn=lambda ctx, prior: ctx,
    )
    out = role.run(_ErrorLLM(), "ctx", [])
    assert out is None


# ── Pipeline ─────────────────────────────────────────────────────────────────


def test_pipeline_returns_last_successful_output() -> None:
    """All stages succeed; final stage output is returned."""
    stage_a = SubRole(
        name="A",
        system_prompt="A",
        user_prompt_fn=lambda ctx, prior: ctx,
    )
    stage_b = SubRole(
        name="B",
        system_prompt="B",
        user_prompt_fn=lambda ctx, prior: ctx,
    )
    llm = MockLLMClient(fixed_response=json.dumps({"stage": "output"}))
    pipeline = Pipeline([stage_a, stage_b])
    result = pipeline.run(llm, "context")
    assert result == {"stage": "output"}


def test_pipeline_skips_failed_stage_and_continues() -> None:
    """If stage B fails, stage C still runs and wins."""
    responses = iter([
        json.dumps({"from": "A"}),  # A succeeds
        "not json",                  # B fails
        json.dumps({"from": "C"}),  # C succeeds
    ])

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            return next(responses)

    stages = [
        SubRole(name="A", system_prompt="A", user_prompt_fn=lambda ctx, p: ctx),
        SubRole(name="B", system_prompt="B", user_prompt_fn=lambda ctx, p: ctx),
        SubRole(name="C", system_prompt="C", user_prompt_fn=lambda ctx, p: ctx),
    ]
    result = Pipeline(stages).run(_SeqLLM(), "ctx")
    assert result == {"from": "C"}


def test_pipeline_trace_records_failure_reason_for_failed_stage() -> None:
    responses = iter([
        "not json",
        json.dumps({"from": "B"}),
    ])

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            return next(responses)

    stages = [
        SubRole(name="A", system_prompt="A", user_prompt_fn=lambda ctx, p: ctx),
        SubRole(name="B", system_prompt="B", user_prompt_fn=lambda ctx, p: ctx),
    ]
    pipeline = Pipeline(stages)
    result = pipeline.run(_SeqLLM(), "ctx")
    trace = pipeline.drain_last_trace()

    assert result == {"from": "B"}
    assert trace[0]["stage_name"] == "A"
    assert trace[0]["success"] is False
    assert trace[0]["fallback_used"] is True
    assert trace[0]["failure_reason"] == "non_json_response"
    assert trace[1]["stage_name"] == "B"
    assert trace[1]["success"] is True
    assert trace[1]["failure_reason"] == ""


def test_pipeline_trace_uses_upstream_rejection_failure_reason_when_metadata_is_present() -> None:
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

    pipeline = Pipeline(
        [SubRole(name="A", system_prompt="A", user_prompt_fn=lambda ctx, p: ctx)]
    )
    result = pipeline.run(_RejectionLLM(), "ctx")
    trace = pipeline.drain_last_trace()

    assert result is None
    assert trace[0]["success"] is False
    assert trace[0]["failure_reason"] == "upstream_rejection:anthropic:credit_balance_too_low"
    assert trace[0]["llm_metadata"]["gateway_upstream_provider"] == "anthropic"


def test_pipeline_trace_includes_llm_metadata_when_available() -> None:
    class _MetadataLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            self._last_call_metadata = {
                "gateway_endpoint": "chat/completions",
                "gateway_status_code": 200,
                "gateway_fallback_used": False,
            }
            return json.dumps({"result": "ok"})

    stage = SubRole(
        name="A",
        system_prompt="A",
        user_prompt_fn=lambda ctx, p: ctx,
    )
    pipeline = Pipeline([stage])
    _ = pipeline.run(_MetadataLLM(), "ctx")
    trace = pipeline.drain_last_trace()

    assert len(trace) == 1
    assert "llm_metadata" in trace[0]
    assert trace[0]["llm_metadata"]["gateway_endpoint"] == "chat/completions"
    assert trace[0]["llm_metadata"]["gateway_status_code"] == 200


def test_pipeline_returns_none_if_all_stages_fail() -> None:
    llm = MockLLMClient(fixed_response="bad")
    stages = [
        SubRole(name="A", system_prompt="A", user_prompt_fn=lambda ctx, p: ctx),
        SubRole(name="B", system_prompt="B", user_prompt_fn=lambda ctx, p: ctx),
    ]
    result = Pipeline(stages).run(llm, "ctx")
    assert result is None


def test_pipeline_trace_records_llm_exception_failure_reason() -> None:
    class _ErrorLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("boom")

    stages = [
        SubRole(name="A", system_prompt="A", user_prompt_fn=lambda ctx, p: ctx),
    ]
    pipeline = Pipeline(stages)
    result = pipeline.run(_ErrorLLM(), "ctx")
    trace = pipeline.drain_last_trace()

    assert result is None
    assert trace[0]["success"] is False
    assert trace[0]["failure_reason"] == "llm_exception:RuntimeError"


def test_pipeline_passes_prior_outputs_to_next_stage() -> None:
    """Stage B's user_prompt_fn receives stage A's output in prior_outputs."""
    received_prior: list[list] = []

    def capture_prior(ctx: str, prior: list) -> str:
        received_prior.append(list(prior))
        return ctx

    responses = iter([
        json.dumps({"from": "A"}),
        json.dumps({"from": "B"}),
    ])

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            return next(responses)

    stages = [
        # Stage A also uses capture_prior so we can assert it received empty prior
        SubRole(name="A", system_prompt="A", user_prompt_fn=capture_prior),
        SubRole(name="B", system_prompt="B", user_prompt_fn=capture_prior),
    ]
    Pipeline(stages).run(_SeqLLM(), "ctx")

    # Stage A received empty prior; stage B received stage A's output
    assert received_prior[0] == []
    assert len(received_prior[1]) == 1
    assert received_prior[1][0]["stage"] == "A"
    assert received_prior[1][0]["output"] == {"from": "A"}


# ── research_pipeline / design_pipeline / build_pipeline / review_pipeline ──


def test_research_pipeline_stages_named_correctly() -> None:
    pipeline = research_pipeline()
    names = [s.name for s in pipeline._stages]
    assert names == ["ScopeFraming", "EvidenceDraft", "RiskChallenge"]


def test_design_pipeline_stages_named_correctly() -> None:
    pipeline = design_pipeline()
    names = [s.name for s in pipeline._stages]
    assert names == ["ArchitectureDraft", "ConstraintCheck", "DecisionFinalizer"]


def test_research_pipeline_progressive_context_contains_prior_stage_outputs() -> None:
    prompts: list[str] = []
    responses = iter(
        [
            json.dumps(
                {
                    "summary": "frame",
                    "risks": ["risk A"],
                    "assumptions": ["assumption A"],
                    "research_areas": ["area A"],
                }
            ),
            json.dumps(
                {
                    "summary": "draft",
                    "risks": ["risk A"],
                    "assumptions": ["assumption A"],
                    "research_areas": ["area A", "area B"],
                }
            ),
            json.dumps(
                {
                    "summary": "final",
                    "risks": ["risk A"],
                    "assumptions": ["assumption A"],
                    "research_areas": ["area A", "area B"],
                }
            ),
        ]
    )

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            prompts.append(user)
            return next(responses)

    result = research_pipeline().run(_SeqLLM(), "objective: research")
    assert result is not None
    assert len(prompts) == 3
    assert "[ScopeFraming output]" not in prompts[0]
    assert "[ScopeFraming output]" in prompts[1]
    assert "[EvidenceDraft output]" not in prompts[1]
    assert "[ScopeFraming output]" in prompts[2]
    assert "[EvidenceDraft output]" in prompts[2]


def test_design_pipeline_progressive_context_contains_prior_stage_outputs() -> None:
    prompts: list[str] = []
    responses = iter(
        [
            json.dumps(
                {
                    "architecture": "layered",
                    "components": ["api"],
                    "constraints": ["python"],
                    "technical_decisions": ["rest"],
                }
            ),
            json.dumps(
                {
                    "architecture": "layered-v2",
                    "components": ["api", "repo"],
                    "constraints": ["python"],
                    "technical_decisions": ["rest", "strict contracts"],
                }
            ),
            json.dumps(
                {
                    "architecture": "layered-final",
                    "components": ["api", "repo"],
                    "constraints": ["python"],
                    "technical_decisions": ["rest", "strict contracts"],
                }
            ),
        ]
    )

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            prompts.append(user)
            return next(responses)

    result = design_pipeline().run(_SeqLLM(), "objective: design")
    assert result is not None
    assert len(prompts) == 3
    assert "[ArchitectureDraft output]" not in prompts[0]
    assert "[ArchitectureDraft output]" in prompts[1]
    assert "[ConstraintCheck output]" not in prompts[1]
    assert "[ArchitectureDraft output]" in prompts[2]
    assert "[ConstraintCheck output]" in prompts[2]


def test_build_pipeline_stages_named_correctly() -> None:
    pipeline = build_pipeline()
    names = [s.name for s in pipeline._stages]
    assert names == ["Architect", "Coder", "Tester"]


def test_review_pipeline_stages_named_correctly() -> None:
    pipeline = review_pipeline()
    names = [s.name for s in pipeline._stages]
    assert names == ["InitialReview", "CounterCheck", "FinalJudgment"]


def test_build_pipeline_runs_with_mock_llm() -> None:
    llm = MockLLMClient(
        fixed_response=json.dumps({
            "architecture": "layered",
            "components": ["api"],
            "interfaces": [],
            "risks": [],
            "status": "done",
            "scope": "backend",
            "implementation_steps": ["step 1"],
            "estimated_effort": "1d",
            "corrections": [],
            "test_strategy": ["unit"],
        })
    )
    result = build_pipeline().run(llm, "objective: build something")
    assert result is not None
    assert "implementation_steps" in result


def test_build_pipeline_progressive_context_contains_prior_stage_outputs() -> None:
    prompts: list[str] = []
    responses = iter(
        [
            json.dumps(
                {
                    "architecture": "layered",
                    "components": ["api"],
                    "interfaces": [],
                    "risks": [],
                }
            ),
            json.dumps(
                {
                    "status": "implemented",
                    "scope": "backend",
                    "implementation_steps": ["step 1"],
                    "estimated_effort": "1d",
                    "corrections": [],
                }
            ),
            json.dumps(
                {
                    "status": "tested",
                    "scope": "backend",
                    "implementation_steps": ["step 1"],
                    "estimated_effort": "1d",
                    "risks": ["risk A"],
                    "test_strategy": ["unit"],
                }
            ),
        ]
    )

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            prompts.append(user)
            return next(responses)

    result = build_pipeline().run(_SeqLLM(), "objective: build something")
    assert result is not None
    assert len(prompts) == 3
    assert "[Architect output]" not in prompts[0]
    assert "[Architect output]" in prompts[1]
    assert "[Coder output]" not in prompts[1]
    assert "[Architect output]" in prompts[2]
    assert "[Coder output]" in prompts[2]


def test_review_pipeline_runs_with_mock_llm() -> None:
    llm = MockLLMClient(
        fixed_response=json.dumps({
            "verdict": "approved",
            "findings": [],
            "summary": "looks good",
            "challenged_findings": [],
        })
    )
    result = review_pipeline().run(llm, "artifacts text here")
    assert result is not None
    assert result["verdict"] == "approved"


def test_review_pipeline_progressive_context_contains_prior_stage_outputs() -> None:
    prompts: list[str] = []
    responses = iter(
        [
            json.dumps({"verdict": "approved", "findings": [], "summary": "initial"}),
            json.dumps(
                {
                    "verdict": "approved",
                    "findings": [],
                    "summary": "counter",
                    "challenged_findings": [],
                }
            ),
            json.dumps({"verdict": "approved", "findings": [], "summary": "final"}),
        ]
    )

    class _SeqLLM(MockLLMClient):
        def complete(self, system: str, user: str) -> str:
            prompts.append(user)
            return next(responses)

    result = review_pipeline().run(_SeqLLM(), "artifacts")
    assert result is not None
    assert len(prompts) == 3
    assert "[InitialReview output]" not in prompts[0]
    assert "[InitialReview output]" in prompts[1]
    assert "[CounterCheck output]" not in prompts[1]
    assert "[InitialReview output]" in prompts[2]
    assert "[CounterCheck output]" in prompts[2]
