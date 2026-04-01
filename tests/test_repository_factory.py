import pytest

from app.schemas.brief import ProjectBrief
from app.schemas.project import (
    Department,
    Project,
    ProjectRecord,
    ProjectStatus,
    Task,
    TaskStatus,
)
from app.state import repository as repository_module
from app.state.repository import (
    InMemoryProjectRepository,
    PostgresProjectRepository,
    _is_true,
    _parse_strict_flag,
    create_repository_from_env,
)


def test_repository_factory_defaults_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STATE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    repository = create_repository_from_env()
    assert isinstance(repository, InMemoryProjectRepository)


def test_repository_factory_treats_blank_backend_as_memory_even_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "   ")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    repository = create_repository_from_env()

    assert isinstance(repository, InMemoryProjectRepository)


def test_repository_factory_falls_back_when_postgres_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STATE_BACKEND_STRICT", raising=False)
    repository = create_repository_from_env()
    assert isinstance(repository, InMemoryProjectRepository)


def test_repository_factory_strict_mode_raises_without_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    with pytest.raises(ValueError):
        create_repository_from_env()


def test_repository_factory_unknown_backend_falls_back_when_non_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unknown-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    repository = create_repository_from_env()

    assert isinstance(repository, InMemoryProjectRepository)


def test_repository_factory_unknown_backend_raises_when_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unknown-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="Unsupported STATE_BACKEND"):
        create_repository_from_env()


def test_repository_factory_unknown_backend_raises_when_strict_env_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unknown-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "not-a-bool")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="Unsupported STATE_BACKEND"):
        create_repository_from_env()


def test_repository_factory_supports_postgresql_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn
            self.initialize_schema_calls = 0

        def initialize_schema(self) -> None:
            self.initialize_schema_calls += 1

    monkeypatch.setenv("STATE_BACKEND", "postgresql")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.delenv("STATE_BACKEND_STRICT", raising=False)
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FakePostgresRepository)

    repository = create_repository_from_env()

    assert isinstance(repository, _FakePostgresRepository)
    assert repository.initialize_schema_calls == 1


@pytest.mark.parametrize("backend", ["in-memory", "inmemory", "memory"])
def test_repository_factory_supports_memory_aliases(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", backend)
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    repository = create_repository_from_env()

    assert isinstance(repository, InMemoryProjectRepository)


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", " TRUE "])
def test_is_true_accepts_truthy_tokens(raw: str) -> None:
    assert _is_true(raw) is True


@pytest.mark.parametrize("raw", [None, "", "0", "false", "off", " no "])
def test_is_true_rejects_non_truthy_tokens(raw: str | None) -> None:
    assert _is_true(raw) is False


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_parse_strict_flag_defaults_to_false_for_unset_or_blank(raw: str | None) -> None:
    assert _parse_strict_flag(raw) is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", " TRUE "])
def test_parse_strict_flag_accepts_truthy_tokens(raw: str) -> None:
    assert _parse_strict_flag(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", "off", " no "])
def test_parse_strict_flag_accepts_false_tokens(raw: str) -> None:
    assert _parse_strict_flag(raw) is False


@pytest.mark.parametrize("raw", ["invalid", "maybe", "2"])
def test_parse_strict_flag_fails_safe_to_true_for_malformed_values(raw: str) -> None:
    assert _parse_strict_flag(raw) is True


def test_repository_factory_uses_postgres_and_initializes_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn
            self.initialize_schema_calls = 0

        def initialize_schema(self) -> None:
            self.initialize_schema_calls += 1

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.delenv("STATE_BACKEND_STRICT", raising=False)
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FakePostgresRepository)

    repository = create_repository_from_env()

    assert isinstance(repository, _FakePostgresRepository)
    assert repository.dsn == "postgresql://example"
    assert repository.initialize_schema_calls == 1


def test_repository_factory_falls_back_when_postgres_init_fails_non_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("db unavailable")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FailingPostgresRepository)

    repository = create_repository_from_env()

    assert isinstance(repository, InMemoryProjectRepository)


def test_repository_factory_strict_mode_reraises_init_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("db unavailable")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FailingPostgresRepository)

    with pytest.raises(RuntimeError, match="db unavailable"):
        create_repository_from_env()


def test_postgres_task_ordering_uses_dependency_topology() -> None:
    tasks = [
        Task(
            id="task-build",
            title="Build scaffold",
            department=Department.BUILD,
            depends_on=["task-design"],
        ),
        Task(
            id="task-design",
            title="Design architecture",
            department=Department.DESIGN,
            depends_on=["task-research"],
        ),
        Task(
            id="task-review",
            title="Review output",
            department=Department.REVIEW,
            depends_on=["task-build", "task-trend"],
        ),
        Task(
            id="task-trend",
            title="Trend analysis",
            department=Department.TREND,
            depends_on=["task-design"],
        ),
        Task(
            id="task-research",
            title="Research baseline",
            department=Department.RESEARCH,
            depends_on=[],
        ),
    ]

    ordered_tasks = PostgresProjectRepository._order_tasks_for_execution(tasks)

    assert [task.id for task in ordered_tasks] == [
        "task-research",
        "task-design",
        "task-build",
        "task-trend",
        "task-review",
    ]


def test_postgres_task_ordering_falls_back_to_original_when_cycle_detected() -> None:
    tasks = [
        Task(
            id="task-a",
            title="Task A",
            department=Department.BUILD,
            depends_on=["task-b"],
        ),
        Task(
            id="task-b",
            title="Task B",
            department=Department.DESIGN,
            depends_on=["task-a"],
        ),
    ]

    ordered_tasks = PostgresProjectRepository._order_tasks_for_execution(tasks)

    assert [task.id for task in ordered_tasks] == ["task-a", "task-b"]


def test_in_memory_repository_save_get_uses_deep_snapshots() -> None:
    repository = InMemoryProjectRepository()
    record = ProjectRecord(
        project=Project(
            id="proj-snapshot",
            status=ProjectStatus.IN_PROGRESS,
            brief=ProjectBrief(
                title="Snapshot test",
                objective="Repository snapshot behavior",
                scope="state",
                constraints=["python"],
                success_criteria=["no aliasing"],
                deadline="2026-06-30",
                stakeholders=["qa"],
                assumptions=["deterministic"],
                raw_request="Repository snapshot behavior",
            ),
        ),
        tasks=[
            Task(
                id="task-1",
                title="Task 1",
                department=Department.BUILD,
                status=TaskStatus.PENDING,
                depends_on=[],
                note="initial",
            )
        ],
    )

    repository.save(record)
    record.tasks[0].note = "mutated-after-save"

    loaded_once = repository.get("proj-snapshot")
    assert loaded_once is not None
    assert loaded_once.tasks[0].note == "initial"

    loaded_once.tasks[0].note = "mutated-after-get"
    loaded_twice = repository.get("proj-snapshot")
    assert loaded_twice is not None
    assert loaded_twice.tasks[0].note == "initial"
