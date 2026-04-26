"""Sub-role pipeline infrastructure for department agents.

Each department can have an internal hierarchy of sub-roles that chain together:
  - Research: ScopeFraming → EvidenceDraft → RiskChallenge
  - Design:   ArchitectureDraft → ConstraintCheck → DecisionFinalizer
  - Build:   Architect → Coder → Tester
  - Review:  InitialReview → CounterCheck → FinalJudgment

A SubRole takes the previous stage's output as additional context for the next
stage, creating a self-correction loop: each stage can see and build upon (or
challenge) what the previous stage produced.

Usage:
    pipeline = Pipeline([architect_role, coder_role, tester_role])
    final_output = pipeline.run(llm_client, initial_context)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.llm.base import LLMClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageRunResult:
    output: dict | None
    failure_reason: str = ""
    llm_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubRole:
    """A single stage in a department's internal pipeline.

    Attributes:
        name:           Human-readable name for logging (e.g. "Architect").
        system_prompt:  The role's persona and output format instructions.
        user_prompt_fn: Callable that receives the initial context string and
                        the accumulated stage outputs so far, and returns the
                        user message to send to the LLM.
        required_keys:  JSON keys that must be present for the output to be
                        considered valid (empty = no validation).
    """

    name: str
    system_prompt: str
    user_prompt_fn: Callable[[str, list[dict]], str]
    required_keys: list[str] = field(default_factory=list)

    def run_with_diagnostics(
        self,
        llm: LLMClient,
        initial_context: str,
        prior_outputs: list[dict],
    ) -> StageRunResult:
        """Execute this sub-role with explicit success/failure diagnostics."""
        user_prompt = self.user_prompt_fn(initial_context, prior_outputs)
        try:
            raw = llm.complete(self.system_prompt, user_prompt)
            llm_metadata = _pop_llm_call_metadata(llm)
            parsed = _try_parse_json(raw)
            if parsed is None:
                failure_reason = _resolve_non_json_failure_reason(llm_metadata)
                logger.warning("SubRole[%s]: LLM returned non-JSON; skipping.", self.name)
                return StageRunResult(
                    output=None,
                    failure_reason=failure_reason,
                    llm_metadata=llm_metadata,
                )
            if self.required_keys:
                missing = [k for k in self.required_keys if k not in parsed]
                if missing:
                    logger.warning(
                        "SubRole[%s]: missing required keys %s; skipping.", self.name, missing
                    )
                    return StageRunResult(
                        output=None,
                        failure_reason="missing_required_keys:" + ",".join(missing),
                        llm_metadata=llm_metadata,
                    )
            return StageRunResult(output=parsed, llm_metadata=llm_metadata)
        except Exception as exc:
            logger.exception("SubRole[%s]: LLM call failed; skipping.", self.name)
            llm_metadata = _pop_llm_call_metadata(llm)
            return StageRunResult(
                output=None,
                failure_reason=f"llm_exception:{exc.__class__.__name__}",
                llm_metadata=llm_metadata,
            )

    def run(self, llm: LLMClient, initial_context: str, prior_outputs: list[dict]) -> dict | None:
        """Execute this sub-role and return parsed JSON dict, or None on failure."""
        return self.run_with_diagnostics(llm, initial_context, prior_outputs).output


class Pipeline:
    """Chains a list of SubRoles, passing each stage's output to the next.

    If a stage fails (returns None), the pipeline continues with the last
    successful output as context.  The final non-None output wins; if all
    stages fail the pipeline returns None (caller should use fallback).
    """

    def __init__(self, stages: list[SubRole]) -> None:
        self._stages = stages
        self._last_trace: list[dict[str, Any]] = []

    def run(self, llm: LLMClient, initial_context: str) -> dict | None:
        """Run all stages and return the final stage's output (or None)."""
        self._last_trace = []
        prior_outputs: list[dict] = []
        last_good: dict | None = None

        for index, stage in enumerate(self._stages):
            stage_result = stage.run_with_diagnostics(llm, initial_context, prior_outputs)
            result = stage_result.output
            trace_entry: dict[str, Any] = {
                "stage_name": stage.name,
                "sequence": index + 1,
                "failure_reason": "",
            }
            if stage_result.llm_metadata:
                trace_entry["llm_metadata"] = stage_result.llm_metadata
            if result is not None:
                prior_outputs.append({"stage": stage.name, "output": result})
                last_good = result
                trace_entry["success"] = True
                trace_entry["fallback_used"] = False
                self._last_trace.append(trace_entry)
            else:
                logger.warning("Pipeline: stage '%s' failed; using previous output.", stage.name)
                trace_entry["success"] = False
                trace_entry["fallback_used"] = True
                trace_entry["failure_reason"] = stage_result.failure_reason
                self._last_trace.append(trace_entry)

        return last_good

    def drain_last_trace(self) -> list[dict[str, Any]]:
        """Return and clear the latest run trace."""
        trace = [dict(entry) for entry in self._last_trace]
        self._last_trace = []
        return trace


def _pop_llm_call_metadata(llm: LLMClient) -> dict[str, Any]:
    pop_fn = getattr(llm, "pop_last_call_metadata", None)
    if not callable(pop_fn):
        return {}
    try:
        metadata = pop_fn()
    except Exception:  # pragma: no cover - defensive path
        logger.exception("SubRole: failed to capture llm call metadata")
        return {}
    if not isinstance(metadata, dict):
        return {}
    return dict(metadata)


def _resolve_non_json_failure_reason(llm_metadata: dict[str, Any]) -> str:
    error_kind = str(llm_metadata.get("gateway_error_kind", "")).strip().lower()
    upstream_rejection = bool(llm_metadata.get("gateway_upstream_rejection", False))
    if error_kind == "upstream_rejection" or upstream_rejection:
        provider = str(llm_metadata.get("gateway_upstream_provider", "")).strip().lower()
        reason = str(llm_metadata.get("gateway_upstream_rejection_reason", "")).strip().lower()
        parts = ["upstream_rejection"]
        if provider:
            parts.append(provider)
        if reason:
            parts.append(reason)
        return ":".join(parts)
    return "non_json_response"


# ---------------------------------------------------------------------------
# Research pipeline: ScopeFraming → EvidenceDraft → RiskChallenge
# ---------------------------------------------------------------------------

_RESEARCH_FRAMING_SYSTEM = (
    "You are a research planner. Frame the objective, enumerate major risks, "
    "and define concrete investigation areas. "
    "Respond ONLY with a valid JSON object with these fields: "
    "summary (string), risks (list of strings), assumptions (list of strings), "
    "research_areas (list of strings)."
)

_RESEARCH_DRAFT_SYSTEM = (
    "You are a research analyst. Given the project context and prior framing, "
    "produce a clearer research draft with evidence-oriented structure. "
    "Respond ONLY with a valid JSON object with these fields: "
    "summary (string), risks (list of strings), assumptions (list of strings), "
    "research_areas (list of strings)."
)

_RESEARCH_CHALLENGE_SYSTEM = (
    "You are a risk challenger. Critically review prior research output, "
    "tighten weak assumptions, and finalize actionable research focus. "
    "Respond ONLY with a valid JSON object with these fields: "
    "summary (string), risks (list of strings), assumptions (list of strings), "
    "research_areas (list of strings)."
)


def _research_framing_user_prompt(ctx: str, _prior: list[dict]) -> str:
    return f"Project brief:\n{ctx}"


def _research_with_prior_user_prompt(ctx: str, prior: list[dict]) -> str:
    parts = [f"Project brief:\n{ctx}"]
    for p in prior:
        parts.append(f"\n[{p['stage']} output]\n{json.dumps(p['output'], ensure_ascii=False)}")
    return "\n".join(parts)


def research_pipeline() -> Pipeline:
    """Return the Research department pipeline: ScopeFraming → EvidenceDraft → RiskChallenge."""
    return Pipeline(
        [
            SubRole(
                name="ScopeFraming",
                system_prompt=_RESEARCH_FRAMING_SYSTEM,
                user_prompt_fn=_research_framing_user_prompt,
                required_keys=["summary", "risks", "assumptions", "research_areas"],
            ),
            SubRole(
                name="EvidenceDraft",
                system_prompt=_RESEARCH_DRAFT_SYSTEM,
                user_prompt_fn=_research_with_prior_user_prompt,
                required_keys=["summary", "risks", "assumptions", "research_areas"],
            ),
            SubRole(
                name="RiskChallenge",
                system_prompt=_RESEARCH_CHALLENGE_SYSTEM,
                user_prompt_fn=_research_with_prior_user_prompt,
                required_keys=["summary", "risks", "assumptions", "research_areas"],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Design pipeline: ArchitectureDraft → ConstraintCheck → DecisionFinalizer
# ---------------------------------------------------------------------------

_DESIGN_DRAFT_SYSTEM = (
    "You are a solution architect drafting the initial architecture. "
    "Respond ONLY with a valid JSON object with these fields: "
    "architecture (string), components (list of strings), "
    "constraints (list of strings), technical_decisions (list of strings)."
)

_DESIGN_CONSTRAINT_CHECK_SYSTEM = (
    "You are a constraint auditor. Review the architecture draft against "
    "constraints and identify required changes. "
    "Respond ONLY with a valid JSON object with these fields: "
    "architecture (string), components (list of strings), "
    "constraints (list of strings), technical_decisions (list of strings)."
)

_DESIGN_FINALIZER_SYSTEM = (
    "You are a technical decision finalizer. Reconcile prior design outputs "
    "into a final coherent architecture decision package. "
    "Respond ONLY with a valid JSON object with these fields: "
    "architecture (string), components (list of strings), "
    "constraints (list of strings), technical_decisions (list of strings)."
)


def _design_draft_user_prompt(ctx: str, _prior: list[dict]) -> str:
    return f"Project brief:\n{ctx}"


def _design_with_prior_user_prompt(ctx: str, prior: list[dict]) -> str:
    parts = [f"Project brief:\n{ctx}"]
    for p in prior:
        parts.append(f"\n[{p['stage']} output]\n{json.dumps(p['output'], ensure_ascii=False)}")
    return "\n".join(parts)


def design_pipeline() -> Pipeline:
    """Return the Design pipeline: ArchitectureDraft → ConstraintCheck → DecisionFinalizer."""
    return Pipeline(
        [
            SubRole(
                name="ArchitectureDraft",
                system_prompt=_DESIGN_DRAFT_SYSTEM,
                user_prompt_fn=_design_draft_user_prompt,
                required_keys=["architecture", "components", "constraints", "technical_decisions"],
            ),
            SubRole(
                name="ConstraintCheck",
                system_prompt=_DESIGN_CONSTRAINT_CHECK_SYSTEM,
                user_prompt_fn=_design_with_prior_user_prompt,
                required_keys=["architecture", "components", "constraints", "technical_decisions"],
            ),
            SubRole(
                name="DecisionFinalizer",
                system_prompt=_DESIGN_FINALIZER_SYSTEM,
                user_prompt_fn=_design_with_prior_user_prompt,
                required_keys=["architecture", "components", "constraints", "technical_decisions"],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Build pipeline:  Architect → Coder → Tester
# ---------------------------------------------------------------------------

_ARCHITECT_SYSTEM = (
    "You are a software architect. Given a project brief, design a clear technical "
    "architecture and break it into implementation components. "
    "Respond ONLY with a valid JSON object with these fields: "
    "architecture (string), components (list of strings), "
    "interfaces (list of strings), risks (list of strings)."
)

_CODER_SYSTEM = (
    "You are a senior software engineer. Given a project brief and an architectural design, "
    "create a concrete implementation plan with step-by-step tasks. "
    "Review the architecture for gaps and correct any issues. "
    "Respond ONLY with a valid JSON object with these fields: "
    "status (string), scope (string), implementation_steps (list of strings), "
    "estimated_effort (string), corrections (list of strings)."
)

_TESTER_SYSTEM = (
    "You are a QA engineer. Given a project brief, architecture, and implementation plan, "
    "design a testing strategy and identify remaining risks. "
    "Review the implementation plan for issues and flag them. "
    "Respond ONLY with a valid JSON object with these fields: "
    "status (string), scope (string), implementation_steps (list of strings), "
    "estimated_effort (string), risks (list of strings), test_strategy (list of strings)."
)


def _architect_user_prompt(ctx: str, _prior: list[dict]) -> str:
    return f"Project brief:\n{ctx}"


def _coder_user_prompt(ctx: str, prior: list[dict]) -> str:
    parts = [f"Project brief:\n{ctx}"]
    for p in prior:
        parts.append(f"\n[{p['stage']} output]\n{json.dumps(p['output'], ensure_ascii=False)}")
    return "\n".join(parts)


def _tester_user_prompt(ctx: str, prior: list[dict]) -> str:
    parts = [f"Project brief:\n{ctx}"]
    for p in prior:
        parts.append(f"\n[{p['stage']} output]\n{json.dumps(p['output'], ensure_ascii=False)}")
    return "\n".join(parts)


def build_pipeline() -> Pipeline:
    """Return the Build department pipeline: Architect → Coder → Tester."""
    return Pipeline(
        [
            SubRole(
                name="Architect",
                system_prompt=_ARCHITECT_SYSTEM,
                user_prompt_fn=_architect_user_prompt,
                required_keys=["architecture", "components"],
            ),
            SubRole(
                name="Coder",
                system_prompt=_CODER_SYSTEM,
                user_prompt_fn=_coder_user_prompt,
                required_keys=["implementation_steps"],
            ),
            SubRole(
                name="Tester",
                system_prompt=_TESTER_SYSTEM,
                user_prompt_fn=_tester_user_prompt,
                required_keys=["implementation_steps", "risks"],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Review pipeline:  InitialReview → CounterCheck → FinalJudgment
# ---------------------------------------------------------------------------

_INITIAL_REVIEW_SYSTEM = (
    "You are a technical reviewer performing an initial assessment. "
    "Evaluate the provided project artifacts against the supplied project brief, "
    "scope, constraints, and explicit success criteria. "
    "Do not require external evidence, repository validation, or deliverables that "
    "the brief does not explicitly ask for. "
    "Review occurs before terminal workflow transition; do not require a final "
    "project status marker (for example completed) inside evidence artifacts. "
    "Treat live_run_evidence.status values such as in_progress as expected "
    "pre-review snapshots unless the brief explicitly states otherwise. "
    "Treat build report status labels as informational unless they directly "
    "contradict explicit success criteria in the brief. "
    "Reject only when artifacts miss explicit success criteria, conflict with the "
    "brief, or introduce unsafe ambiguity. "
    "Respond ONLY with a valid JSON object with these fields: "
    "verdict (string: 'approved' or 'changes_requested'), "
    "findings (list of strings), summary (string)."
)

_COUNTER_CHECK_SYSTEM = (
    "You are a senior reviewer performing a counter-check. "
    "Given the project brief, the artifacts, and an initial review, "
    "challenge the initial findings: "
    "are the concerns valid? Were important issues missed? Correct any errors. "
    "Do not treat pre-review status snapshots as missing completion evidence. "
    "Do not add new obligations that are outside the supplied brief. "
    "Respond ONLY with a valid JSON object with these fields: "
    "verdict (string: 'approved' or 'changes_requested'), "
    "findings (list of strings), summary (string), "
    "challenged_findings (list of strings)."
)

_FINAL_JUDGMENT_SYSTEM = (
    "You are a review board lead making the final judgment. "
    "Given the project brief, the artifacts, the initial review, and the counter-check, "
    "produce a final verdict. "
    "Weigh all findings and counter-arguments; be decisive. "
    "The decision must stay inside the brief's explicit scope and success criteria. "
    "Do not require a terminal workflow status inside artifacts because review "
    "runs before final status transition. "
    "Respond ONLY with a valid JSON object with these fields: "
    "verdict (string: 'approved' or 'changes_requested'), "
    "findings (list of strings), summary (string)."
)


def _initial_review_user_prompt(ctx: str, _prior: list[dict]) -> str:
    return f"Brief and artifacts to review:\n{ctx}"


def _counter_check_user_prompt(ctx: str, prior: list[dict]) -> str:
    parts = [f"Brief and artifacts to review:\n{ctx}"]
    for p in prior:
        parts.append(f"\n[{p['stage']} output]\n{json.dumps(p['output'], ensure_ascii=False)}")
    return "\n".join(parts)


def _final_judgment_user_prompt(ctx: str, prior: list[dict]) -> str:
    parts = [f"Brief and artifacts to review:\n{ctx}"]
    for p in prior:
        parts.append(f"\n[{p['stage']} output]\n{json.dumps(p['output'], ensure_ascii=False)}")
    return "\n".join(parts)


def review_pipeline() -> Pipeline:
    """Return the Review department pipeline: InitialReview → CounterCheck → FinalJudgment."""
    return Pipeline(
        [
            SubRole(
                name="InitialReview",
                system_prompt=_INITIAL_REVIEW_SYSTEM,
                user_prompt_fn=_initial_review_user_prompt,
                required_keys=["verdict", "findings"],
            ),
            SubRole(
                name="CounterCheck",
                system_prompt=_COUNTER_CHECK_SYSTEM,
                user_prompt_fn=_counter_check_user_prompt,
                required_keys=["verdict", "findings"],
            ),
            SubRole(
                name="FinalJudgment",
                system_prompt=_FINAL_JUDGMENT_SYSTEM,
                user_prompt_fn=_final_judgment_user_prompt,
                required_keys=["verdict", "findings"],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_parse_json(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        extracted = _extract_first_json_object(stripped)
        if extracted is None:
            return None
        try:
            parsed = json.loads(extracted)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from free-form text."""
    start_index = -1
    depth = 0
    in_string = False
    escape = False

    for index, char in enumerate(text):
        if start_index == -1:
            if char == "{":
                start_index = index
                depth = 1
            continue

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]

    return None
