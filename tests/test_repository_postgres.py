import os
import uuid

import pytest

from app.schemas.brief import ProjectBrief
from app.schemas.project import (
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
from app.state.repository import PostgresProjectRepository


def _test_database_url() -> str | None:
    return os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(
    not _test_database_url(),
    reason="Set TEST_DATABASE_URL to run PostgreSQL repository integration tests.",
)
def test_postgres_repository_roundtrip() -> None:
    pytest.importorskip("psycopg")
    repository = PostgresProjectRepository(dsn=_test_database_url() or "")
    repository.initialize_schema()

    project_id = f"proj-{uuid.uuid4()}"
    record = ProjectRecord(
        project=Project(
            id=project_id,
            status=ProjectStatus.IN_PROGRESS,
            brief=ProjectBrief(
                title="DB test",
                objective="Repository roundtrip",
                scope="state layer",
                constraints=["postgres"],
                success_criteria=["record persisted"],
                deadline="2026-05-01",
                stakeholders=["qa"],
                assumptions=["integration db available"],
                raw_request="Repository roundtrip",
            ),
        ),
        tasks=[
            Task(
                id="task-1",
                title="Store project",
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
                findings=[],
            )
        ],
        checkpoints=[
            Checkpoint(
                id="checkpoint-1",
                name="gate",
                approved=True,
                approver="system",
                note="ok",
            )
        ],
        approvals=[
            ApprovalRequest(
                id="approval-1",
                action_type=ApprovalActionType.EXTERNAL_API_SEND,
                reason="test",
            )
        ],
        history=["draft -> intake_pending"],
        events=[
            HistoryEvent(
                event_type=HistoryEventType.STATE_TRANSITION,
                actor="test",
                reason="roundtrip",
                metadata={"from": "draft", "to": "intake_pending"},
            )
        ],
    )

    repository.save(record)
    loaded = repository.get(project_id)

    assert loaded is not None
    assert loaded.project.id == project_id
    assert loaded.tasks[0].id == "task-1"
    assert loaded.artifacts[0].artifact_type == "build_report"
    assert loaded.reviews[0].verdict == "approved"
    assert loaded.checkpoints[0].approved is True
    assert loaded.approvals[0].action_type == ApprovalActionType.EXTERNAL_API_SEND
    assert loaded.events[0].event_type == HistoryEventType.STATE_TRANSITION
    assert loaded.project.policy.strict_mode is False
