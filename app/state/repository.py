import json
import os
from abc import ABC, abstractmethod

from app.runtime_flags import parse_env_bool, parse_strict_env_flag
from app.schemas.brief import ProjectBrief
from app.schemas.project import (
    ApprovalRequest,
    Artifact,
    Checkpoint,
    HistoryEvent,
    Project,
    ProjectPolicy,
    ProjectRecord,
    Review,
    Task,
)


class ProjectRepository(ABC):
    @abstractmethod
    def initialize_schema(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def save(self, record: ProjectRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, project_id: str) -> ProjectRecord | None:
        raise NotImplementedError


class InMemoryProjectRepository(ProjectRepository):
    def __init__(self) -> None:
        self._store: dict[str, ProjectRecord] = {}

    @staticmethod
    def _snapshot(record: ProjectRecord) -> ProjectRecord:
        return record.model_copy(deep=True)

    def initialize_schema(self) -> None:
        return None

    def save(self, record: ProjectRecord) -> None:
        self._store[record.project.id] = self._snapshot(record)

    def get(self, project_id: str) -> ProjectRecord | None:
        stored = self._store.get(project_id)
        if stored is None:
            return None
        return self._snapshot(stored)


class PostgresProjectRepository(ProjectRepository):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _connect(self):
        try:
            import psycopg
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "psycopg is required for PostgresProjectRepository. "
                "Install with: pip install -e .[postgres]"
            ) from exc
        return psycopg.connect(self.dsn)

    @staticmethod
    def _load_json(value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _order_tasks_for_execution(tasks: list[Task]) -> list[Task]:
        if len(tasks) < 2:
            return tasks

        task_ids = {task.id for task in tasks}
        position_by_id = {task.id: index for index, task in enumerate(tasks)}
        dependents_by_id: dict[str, list[str]] = {task.id: [] for task in tasks}
        inbound_count_by_id: dict[str, int] = {task.id: 0 for task in tasks}

        for task in tasks:
            local_dependencies = {
                dependency_id for dependency_id in task.depends_on if dependency_id in task_ids
            }
            inbound_count_by_id[task.id] = len(local_dependencies)
            for dependency_id in local_dependencies:
                dependents_by_id[dependency_id].append(task.id)

        ready_task_ids = sorted(
            [task.id for task in tasks if inbound_count_by_id[task.id] == 0],
            key=lambda task_id: position_by_id[task_id],
        )

        ordered_task_ids: list[str] = []
        while ready_task_ids:
            current_task_id = ready_task_ids.pop(0)
            ordered_task_ids.append(current_task_id)
            for dependent_task_id in dependents_by_id[current_task_id]:
                inbound_count_by_id[dependent_task_id] -= 1
                if inbound_count_by_id[dependent_task_id] == 0:
                    ready_task_ids.append(dependent_task_id)
            ready_task_ids.sort(key=lambda task_id: position_by_id[task_id])

        # Keep original sequence as a safe fallback when dependencies are cyclic/invalid.
        if len(ordered_task_ids) != len(tasks):
            return tasks

        tasks_by_id = {task.id: task for task in tasks}
        return [tasks_by_id[task_id] for task_id in ordered_task_ids]

    def initialize_schema(self) -> None:
        create_sql = """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            brief_json JSONB NOT NULL,
            policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            department TEXT NOT NULL,
            status TEXT NOT NULL,
            depends_on JSONB NOT NULL,
            note TEXT NOT NULL,
            PRIMARY KEY (id, project_id)
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            content JSONB NOT NULL,
            PRIMARY KEY (id, project_id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            findings JSONB NOT NULL,
            PRIMARY KEY (id, project_id)
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            approved BOOLEAN NOT NULL,
            approver TEXT NOT NULL,
            note TEXT NOT NULL,
            PRIMARY KEY (id, project_id)
        );

        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            action_type TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            decision_note TEXT NOT NULL,
            PRIMARY KEY (id, project_id)
        );

        CREATE TABLE IF NOT EXISTS project_history (
            project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            events JSONB NOT NULL
        );

        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS policy_json JSONB NOT NULL DEFAULT '{}'::jsonb;
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(create_sql)
            conn.commit()

    def save(self, record: ProjectRecord) -> None:
        project = record.project
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO projects (id, status, brief_json, policy_json, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET status = EXCLUDED.status,
                        brief_json = EXCLUDED.brief_json,
                        policy_json = EXCLUDED.policy_json,
                        updated_at = NOW()
                    """,
                    (
                        project.id,
                        project.status.value,
                        json.dumps(project.brief.model_dump()),
                        json.dumps(project.policy.model_dump()),
                    ),
                )
                cursor.execute("DELETE FROM tasks WHERE project_id = %s", (project.id,))
                cursor.execute("DELETE FROM artifacts WHERE project_id = %s", (project.id,))
                cursor.execute("DELETE FROM reviews WHERE project_id = %s", (project.id,))
                cursor.execute("DELETE FROM checkpoints WHERE project_id = %s", (project.id,))
                cursor.execute("DELETE FROM approvals WHERE project_id = %s", (project.id,))
                cursor.execute("DELETE FROM project_history WHERE project_id = %s", (project.id,))

                for task in record.tasks:
                    cursor.execute(
                        """
                        INSERT INTO tasks
                        (id, project_id, title, department, status, depends_on, note)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            task.id,
                            project.id,
                            task.title,
                            task.department.value,
                            task.status.value,
                            json.dumps(task.depends_on),
                            task.note,
                        ),
                    )
                for artifact in record.artifacts:
                    cursor.execute(
                        """
                        INSERT INTO artifacts
                        (id, project_id, task_id, artifact_type, content)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            artifact.id,
                            project.id,
                            artifact.task_id,
                            artifact.artifact_type,
                            json.dumps(artifact.content),
                        ),
                    )
                for review in record.reviews:
                    cursor.execute(
                        """
                        INSERT INTO reviews
                        (id, project_id, task_id, verdict, findings)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            review.id,
                            project.id,
                            review.task_id,
                            review.verdict,
                            json.dumps(review.findings),
                        ),
                    )
                for checkpoint in record.checkpoints:
                    cursor.execute(
                        """
                        INSERT INTO checkpoints
                        (id, project_id, name, approved, approver, note)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            checkpoint.id,
                            project.id,
                            checkpoint.name,
                            checkpoint.approved,
                            checkpoint.approver,
                            checkpoint.note,
                        ),
                    )
                for approval in record.approvals:
                    cursor.execute(
                        """
                        INSERT INTO approvals
                        (id, project_id, action_type, status, reason, requested_by, decision_note)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            approval.id,
                            project.id,
                            approval.action_type.value,
                            approval.status.value,
                            approval.reason,
                            approval.requested_by,
                            approval.decision_note,
                        ),
                    )

                cursor.execute(
                    """
                    INSERT INTO project_history (project_id, events)
                    VALUES (%s, %s::jsonb)
                    """,
                    (
                        project.id,
                        json.dumps(
                            {
                                "history": record.history,
                                "events": [event.model_dump() for event in record.events],
                            }
                        ),
                    ),
                )
            conn.commit()

    def get(self, project_id: str) -> ProjectRecord | None:
        try:
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "psycopg is required for PostgresProjectRepository. "
                "Install with: pip install -e .[postgres]"
            ) from exc

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT id, status, brief_json, policy_json FROM projects WHERE id = %s",
                    (project_id,),
                )
                project_row = cursor.fetchone()
                if not project_row:
                    return None

                cursor.execute(
                    """
                    SELECT id, title, department, status, depends_on, note
                    FROM tasks WHERE project_id = %s ORDER BY id
                    """,
                    (project_id,),
                )
                task_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT id, task_id, artifact_type, content
                    FROM artifacts WHERE project_id = %s ORDER BY id
                    """,
                    (project_id,),
                )
                artifact_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT id, task_id, verdict, findings
                    FROM reviews WHERE project_id = %s ORDER BY id
                    """,
                    (project_id,),
                )
                review_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT id, name, approved, approver, note
                    FROM checkpoints WHERE project_id = %s ORDER BY id
                    """,
                    (project_id,),
                )
                checkpoint_rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT id, action_type, status, reason, requested_by, decision_note
                    FROM approvals WHERE project_id = %s ORDER BY id
                    """,
                    (project_id,),
                )
                approval_rows = cursor.fetchall()

                cursor.execute(
                    "SELECT events FROM project_history WHERE project_id = %s",
                    (project_id,),
                )
                history_row = cursor.fetchone()

        brief_payload = self._load_json(project_row["brief_json"])
        project = Project(
            id=project_row["id"],
            status=project_row["status"],
            brief=ProjectBrief.model_validate(brief_payload),
            policy=ProjectPolicy.model_validate(self._load_json(project_row["policy_json"]) or {}),
        )
        tasks = [
            Task(
                id=row["id"],
                title=row["title"],
                department=row["department"],
                status=row["status"],
                depends_on=self._load_json(row["depends_on"]) or [],
                note=row["note"],
            )
            for row in task_rows
        ]
        tasks = self._order_tasks_for_execution(tasks)
        artifacts = [
            Artifact(
                id=row["id"],
                task_id=row["task_id"],
                artifact_type=row["artifact_type"],
                content=self._load_json(row["content"]) or {},
            )
            for row in artifact_rows
        ]
        reviews = [
            Review(
                id=row["id"],
                task_id=row["task_id"],
                verdict=row["verdict"],
                findings=self._load_json(row["findings"]) or [],
            )
            for row in review_rows
        ]
        checkpoints = [
            Checkpoint(
                id=row["id"],
                name=row["name"],
                approved=row["approved"],
                approver=row["approver"],
                note=row["note"],
            )
            for row in checkpoint_rows
        ]
        approvals = [
            ApprovalRequest(
                id=row["id"],
                action_type=row["action_type"],
                status=row["status"],
                reason=row["reason"],
                requested_by=row["requested_by"],
                decision_note=row["decision_note"],
            )
            for row in approval_rows
        ]
        history_payload = self._load_json(history_row["events"]) if history_row else {}
        history: list[str] = []
        events: list[HistoryEvent] = []
        if isinstance(history_payload, dict):
            history = history_payload.get("history", []) or []
            raw_events = history_payload.get("events", []) or []
            events = [HistoryEvent.model_validate(raw_event) for raw_event in raw_events]
        elif isinstance(history_payload, list):
            if history_payload and isinstance(history_payload[0], dict):
                events = [HistoryEvent.model_validate(raw_event) for raw_event in history_payload]
            else:
                history = history_payload

        return ProjectRecord(
            project=project,
            tasks=tasks,
            artifacts=artifacts,
            reviews=reviews,
            checkpoints=checkpoints,
            approvals=approvals,
            history=history or [],
            events=events,
        )


def _is_true(value: str | None) -> bool:
    return parse_env_bool(value, default=False)


def _parse_strict_flag(value: str | None) -> bool:
    return parse_strict_env_flag(value)


def create_repository_from_env() -> ProjectRepository:
    backend_raw = (os.getenv("STATE_BACKEND", "memory") or "memory").strip().lower()
    if not backend_raw:
        backend_raw = "memory"
    backend_aliases = {
        "memory": "memory",
        "in-memory": "memory",
        "inmemory": "memory",
        "postgres": "postgres",
        "postgresql": "postgres",
    }
    backend = backend_aliases.get(backend_raw, backend_raw)
    strict = parse_strict_env_flag(os.getenv("STATE_BACKEND_STRICT"))
    if backend not in {"memory", "postgres"}:
        if strict:
            raise ValueError(f"Unsupported STATE_BACKEND: {backend}")
        return InMemoryProjectRepository()
    if backend == "postgres":
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            if strict:
                raise ValueError("STATE_BACKEND=postgres requires DATABASE_URL")
            return InMemoryProjectRepository()
        try:
            repository = PostgresProjectRepository(dsn=dsn)
            repository.initialize_schema()
            return repository
        except Exception:
            if strict:
                raise
            return InMemoryProjectRepository()
    return InMemoryProjectRepository()
