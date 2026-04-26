import uuid

from app.orchestrator.service import PMOrchestrator
from app.schemas.brief import ProjectBrief
from app.schemas.project import (
    ActorContext,
    ActorRole,
    ActorType,
    ApprovalActionType,
    ApprovalRequest,
    Artifact,
    Checkpoint,
    Department,
    HistoryEvent,
    HistoryEventType,
    Project,
    ProjectRecord,
    ProjectStatus,
    Review,
    Task,
    TaskStatus,
)
from app.state.repository import SqliteProjectRepository


def _build_brief(name: str) -> ProjectBrief:
    return ProjectBrief(
        title=name,
        objective=f"{name} objective",
        scope="repository sqlite persistence",
        constraints=["sqlite"],
        success_criteria=["persisted project"],
        deadline="2026-08-01",
        stakeholders=["qa"],
        assumptions=["local filesystem available"],
        raw_request=f"{name} raw request",
    )


def test_sqlite_repository_roundtrip_across_instances(tmp_path) -> None:
    db_path = tmp_path / "state.sqlite3"
    project_id = f"proj-{uuid.uuid4()}"

    repo_first = SqliteProjectRepository(str(db_path))
    repo_first.initialize_schema()
    repo_first.save(
        ProjectRecord(
            project=Project(
                id=project_id,
                status=ProjectStatus.IN_PROGRESS,
                brief=_build_brief("sqlite-roundtrip"),
            ),
            tasks=[
                Task(
                    id="task-1",
                    title="Persist state",
                    department=Department.BUILD,
                    status=TaskStatus.DONE,
                )
            ],
            artifacts=[
                Artifact(
                    id="artifact-1",
                    task_id="task-1",
                    artifact_type="build_report",
                    content={"status": "ok"},
                )
            ],
            reviews=[
                Review(
                    id="review-1",
                    task_id="task-1",
                    verdict="approved",
                )
            ],
            checkpoints=[
                Checkpoint(
                    id="checkpoint-1",
                    name="gate",
                    approved=True,
                    approver="operator",
                    note="checkpoint approved",
                )
            ],
            approvals=[
                ApprovalRequest(
                    id="approval-1",
                    action_type=ApprovalActionType.EXTERNAL_API_SEND,
                    reason="approval check",
                )
            ],
            history=["draft -> in_progress"],
            events=[
                HistoryEvent(
                    event_type=HistoryEventType.STATE_TRANSITION,
                    actor="operator-1",
                    reason="transition",
                    metadata={"from": "draft", "to": "in_progress"},
                )
            ],
        )
    )

    repo_second = SqliteProjectRepository(str(db_path))
    repo_second.initialize_schema()
    loaded = repo_second.get(project_id)

    assert loaded is not None
    assert loaded.project.id == project_id
    assert loaded.project.status == ProjectStatus.IN_PROGRESS
    assert loaded.tasks[0].status == TaskStatus.DONE
    assert loaded.artifacts[0].artifact_type == "build_report"
    assert loaded.reviews[0].verdict == "approved"
    assert loaded.checkpoints[0].approved is True
    assert loaded.approvals[0].action_type == ApprovalActionType.EXTERNAL_API_SEND
    assert loaded.events[0].event_type == HistoryEventType.STATE_TRANSITION
    repo_first.close()
    repo_second.close()


def test_sqlite_orchestrator_persists_audit_across_repository_reopen(tmp_path) -> None:
    db_path = tmp_path / "orchestrator.sqlite3"

    repo_first = SqliteProjectRepository(str(db_path))
    repo_first.initialize_schema()
    orchestrator_first = PMOrchestrator(repository=repo_first)

    waiting = orchestrator_first.run(
        _build_brief("sqlite-audit"),
        trend_provider_name="gemini",
    )
    project_id = waiting.summary.project_id
    assert waiting.summary.status == ProjectStatus.WAITING_APPROVAL

    repo_second = SqliteProjectRepository(str(db_path))
    repo_second.initialize_schema()
    orchestrator_second = PMOrchestrator(repository=repo_second)
    audit_before = orchestrator_second.get_project_audit(project_id)
    assert audit_before.status == ProjectStatus.WAITING_APPROVAL
    assert any(
        approval.action_type == ApprovalActionType.EXTERNAL_API_SEND
        for approval in audit_before.approvals
    )

    resumed = orchestrator_second.resume_from_approval(
        project_id=project_id,
        approved_actions=[ApprovalActionType.EXTERNAL_API_SEND],
        actor=ActorContext(
            actor_id="approver-1",
            actor_role=ActorRole.APPROVER,
            actor_type=ActorType.HUMAN,
        ),
        note="sqlite approval",
        trend_provider_name="gemini",
    )
    assert resumed.summary.status == ProjectStatus.COMPLETED

    repo_third = SqliteProjectRepository(str(db_path))
    repo_third.initialize_schema()
    orchestrator_third = PMOrchestrator(repository=repo_third)
    audit_after = orchestrator_third.get_project_audit(project_id)

    assert audit_after.status == ProjectStatus.COMPLETED
    assert any(
        event.event_type == HistoryEventType.APPROVAL_APPROVED
        for event in audit_after.events
    )
    repo_first.close()
    repo_second.close()
    repo_third.close()


def test_sqlite_repository_sets_busy_timeout_and_wal_mode(tmp_path) -> None:
    db_path = tmp_path / "pragmas.sqlite3"
    repository = SqliteProjectRepository(str(db_path))
    repository.initialize_schema()

    busy_timeout = repository._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    journal_mode = repository._conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert busy_timeout == 5000
    assert str(journal_mode).lower() == "wal"
    repository.close()
