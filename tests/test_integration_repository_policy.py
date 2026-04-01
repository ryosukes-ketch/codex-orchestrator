import pytest

from app.orchestrator.service import PMOrchestrator
from app.schemas.brief import ProjectBrief
from app.schemas.project import (
    ActorContext,
    ActorRole,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    HistoryEventType,
    ProjectStatus,
)
from app.state import repository as repository_module
from app.state.repository import InMemoryProjectRepository


def _brief() -> ProjectBrief:
    return ProjectBrief(
        title="Repository integration",
        objective="Validate repository factory + orchestrator interaction",
        scope="state and approval flow",
        constraints=["python", "fastapi"],
        success_criteria=["deterministic transitions"],
        deadline="2026-06-30",
        stakeholders=["platform"],
        assumptions=["local deterministic run"],
        raw_request="Validate repository factory + orchestrator interaction",
    )


def _approver() -> ActorContext:
    return ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)


def test_orchestrator_init_respects_strict_repository_config_without_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")

    with pytest.raises(ValueError, match="requires DATABASE_URL"):
        PMOrchestrator()


def test_orchestrator_falls_back_to_in_memory_and_completes_approval_flow_when_non_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")

    orchestrator = PMOrchestrator()
    assert isinstance(orchestrator.repository, InMemoryProjectRepository)

    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    assert waiting.summary.status == ProjectStatus.WAITING_APPROVAL

    resumed = orchestrator.resume_from_approval(
        project_id=waiting.record.project.id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert resumed.summary.status == ProjectStatus.COMPLETED


def test_orchestrator_init_reraises_postgres_initialization_failure_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("postgres unavailable")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://integration")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.setattr(
        repository_module,
        "PostgresProjectRepository",
        _FailingPostgresRepository,
    )

    with pytest.raises(RuntimeError, match="postgres unavailable"):
        PMOrchestrator()


def test_orchestrator_non_strict_fallback_handles_postgres_init_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("postgres unavailable")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://integration")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")
    monkeypatch.setattr(
        repository_module,
        "PostgresProjectRepository",
        _FailingPostgresRepository,
    )

    orchestrator = PMOrchestrator()
    assert isinstance(orchestrator.repository, InMemoryProjectRepository)

    result = orchestrator.run(_brief(), trend_provider_name="mock")
    assert result.summary.status == ProjectStatus.COMPLETED


def test_orchestrator_unknown_backend_falls_back_to_memory_when_non_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unsupported-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    orchestrator = PMOrchestrator()
    assert isinstance(orchestrator.repository, InMemoryProjectRepository)

    result = orchestrator.run(_brief(), trend_provider_name="mock")
    assert result.summary.status == ProjectStatus.COMPLETED


def test_orchestrator_unknown_backend_raises_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unsupported-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="Unsupported STATE_BACKEND"):
        PMOrchestrator()


def test_orchestrator_unknown_backend_raises_when_strict_env_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unsupported-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "not-a-bool")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="Unsupported STATE_BACKEND"):
        PMOrchestrator()


def test_orchestrator_blank_backend_uses_memory_repository_even_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "   ")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    orchestrator = PMOrchestrator()
    assert isinstance(orchestrator.repository, InMemoryProjectRepository)

    result = orchestrator.run(_brief(), trend_provider_name="mock")
    assert result.summary.status == ProjectStatus.COMPLETED


def test_orchestrator_postgresql_alias_uses_postgres_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn
            self.initialize_schema_calls = 0

        def initialize_schema(self) -> None:
            self.initialize_schema_calls += 1

    monkeypatch.setenv("STATE_BACKEND", "postgresql")
    monkeypatch.setenv("DATABASE_URL", "postgresql://integration")
    monkeypatch.delenv("STATE_BACKEND_STRICT", raising=False)
    monkeypatch.setattr(
        repository_module,
        "PostgresProjectRepository",
        _FakePostgresRepository,
    )

    orchestrator = PMOrchestrator()
    assert isinstance(orchestrator.repository, _FakePostgresRepository)
    assert orchestrator.repository.initialize_schema_calls == 1


def test_orchestrator_returned_record_mutation_does_not_corrupt_repository_state() -> None:
    repository = InMemoryProjectRepository()
    orchestrator = PMOrchestrator(repository=repository)

    waiting = orchestrator.run(_brief(), trend_provider_name="gemini")
    assert waiting.summary.status == ProjectStatus.WAITING_APPROVAL
    waiting.record.approvals[0].status = ApprovalStatus.APPROVED
    waiting.record.tasks[3].status = waiting.record.tasks[0].status

    resumed = orchestrator.resume_from_approval(
        project_id=waiting.record.project.id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )

    assert resumed.summary.status == ProjectStatus.COMPLETED


def test_repo_manual_conflict_precedence_survives_orchestrator_reinstantiation() -> None:
    repository = InMemoryProjectRepository()
    run_orchestrator = PMOrchestrator(repository=repository)

    waiting = run_orchestrator.run(_brief(), trend_provider_name="gemini")
    assert waiting.summary.status == ProjectStatus.WAITING_APPROVAL
    project_id = waiting.record.project.id

    reject_orchestrator = PMOrchestrator(repository=repository)
    rejected = reject_orchestrator.reject_approval(
        project_id=project_id,
        rejected_actions=["external_api_send"],
        actor=_approver(),
        reason="Reject in separate orchestrator instance.",
    )
    assert rejected.summary.status == ProjectStatus.REVISION_REQUESTED

    resume_orchestrator = PMOrchestrator(repository=repository)
    with pytest.raises(ValueError, match="current: revision_requested"):
        resume_orchestrator.resume_from_approval(
            project_id=project_id,
            approved_actions=["external_api_send"],
            actor=_approver(),
            trend_provider_name="gemini",
        )


def test_repository_backed_partial_approval_flow_remains_consistent_across_orchestrator_instances(
) -> None:
    repository = InMemoryProjectRepository()
    run_orchestrator = PMOrchestrator(repository=repository)
    waiting = run_orchestrator.run(_brief(), trend_provider_name="gemini")
    assert waiting.summary.status == ProjectStatus.WAITING_APPROVAL
    project_id = waiting.record.project.id

    record = repository.get(project_id)
    assert record is not None
    record.approvals.append(
        ApprovalRequest(
            id="approval-bulk-modify-repo-partial",
            action_type=ApprovalActionType.BULK_MODIFY,
            status=ApprovalStatus.PENDING,
            reason="Bulk modify requires explicit approval.",
            requested_by="system",
        )
    )
    repository.save(record)

    first_partial_orchestrator = PMOrchestrator(repository=repository)
    first_partial = first_partial_orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert first_partial.summary.status == ProjectStatus.WAITING_APPROVAL

    second_partial_orchestrator = PMOrchestrator(repository=repository)
    second_partial = second_partial_orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["external_api_send"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert second_partial.summary.status == ProjectStatus.WAITING_APPROVAL

    complete_orchestrator = PMOrchestrator(repository=repository)
    completed = complete_orchestrator.resume_from_approval(
        project_id=project_id,
        approved_actions=["bulk_modify"],
        actor=_approver(),
        trend_provider_name="gemini",
    )
    assert completed.summary.status == ProjectStatus.COMPLETED

    audit = complete_orchestrator.get_project_audit(project_id)
    partial_events = [
        event
        for event in audit.events
        if event.event_type == HistoryEventType.RESUME_TRIGGERED
        and event.metadata.get("mode") == "approval_resume_partial"
    ]
    assert len(partial_events) == 1
