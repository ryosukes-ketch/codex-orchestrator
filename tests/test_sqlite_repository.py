import pytest

from app.orchestrator.service import PMOrchestrator
from app.schemas.brief import ProjectBrief
from app.schemas.project import ProjectStatus
from app.state.repository import SqliteProjectRepository


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_codex.db")
    repo = SqliteProjectRepository(db_path=db_path)
    repo.initialize_schema()
    yield repo
    repo.close()


@pytest.fixture
def orchestrator_sqlite(tmp_db):
    return PMOrchestrator(repository=tmp_db)


class TestSqliteRepositoryBasic:
    def test_save_and_get_returns_record(self, orchestrator_sqlite):
        brief = ProjectBrief(
            objective="Test objective",
            raw_request="Test raw request",
        )
        result = orchestrator_sqlite.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id

        repo = orchestrator_sqlite.repository
        record = repo.get(project_id)
        assert record is not None
        assert record.project.id == project_id

    def test_get_missing_returns_none(self, tmp_db):
        assert tmp_db.get("nonexistent-id") is None

    def test_status_persists_as_completed(self, orchestrator_sqlite):
        brief = ProjectBrief(
            objective="Persistence test",
            raw_request="Check status persists",
        )
        result = orchestrator_sqlite.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id

        record = orchestrator_sqlite.repository.get(project_id)
        assert record.project.status == ProjectStatus.COMPLETED

    def test_tasks_persisted(self, orchestrator_sqlite):
        brief = ProjectBrief(
            objective="Task persistence",
            raw_request="Check tasks saved",
        )
        result = orchestrator_sqlite.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id

        record = orchestrator_sqlite.repository.get(project_id)
        assert len(record.tasks) == 5  # research, design, build, trend, review

    def test_artifacts_persisted(self, orchestrator_sqlite):
        brief = ProjectBrief(
            objective="Artifact persistence",
            raw_request="Check artifacts saved",
        )
        result = orchestrator_sqlite.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id

        record = orchestrator_sqlite.repository.get(project_id)
        assert len(record.artifacts) > 0

    def test_events_persisted(self, orchestrator_sqlite):
        brief = ProjectBrief(
            objective="Event persistence",
            raw_request="Check events saved",
        )
        result = orchestrator_sqlite.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id

        record = orchestrator_sqlite.repository.get(project_id)
        assert len(record.events) > 0

    def test_history_persisted(self, orchestrator_sqlite):
        brief = ProjectBrief(
            objective="History persistence",
            raw_request="Check history saved",
        )
        result = orchestrator_sqlite.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id

        record = orchestrator_sqlite.repository.get(project_id)
        assert len(record.history) > 0


class TestSqliteRepositoryRestartSimulation:
    def test_record_survives_reopen(self, tmp_path):
        """Simulates server restart: close and reopen the DB file."""
        db_path = str(tmp_path / "restart_test.db")

        # First session: create a project
        repo1 = SqliteProjectRepository(db_path=db_path)
        repo1.initialize_schema()
        orchestrator1 = PMOrchestrator(repository=repo1)
        brief = ProjectBrief(
            objective="Restart test",
            raw_request="Must survive restart",
        )
        result = orchestrator1.run(brief=brief, trend_provider_name="mock")
        project_id = result.summary.project_id
        repo1.close()

        # Second session: reopen and retrieve
        repo2 = SqliteProjectRepository(db_path=db_path)
        repo2.initialize_schema()
        record = repo2.get(project_id)
        repo2.close()

        assert record is not None
        assert record.project.id == project_id
        assert record.project.status == ProjectStatus.COMPLETED

    def test_approval_state_survives_reopen(self, tmp_path):
        """Approval waiting state must survive restart."""
        db_path = str(tmp_path / "approval_restart.db")

        repo1 = SqliteProjectRepository(db_path=db_path)
        repo1.initialize_schema()
        orchestrator1 = PMOrchestrator(repository=repo1)
        brief = ProjectBrief(
            objective="Approval restart test",
            raw_request="Waiting approval must persist",
        )
        # gemini-flash-lite-latest triggers waiting_approval
        result = orchestrator1.run(
            brief=brief, trend_provider_name="gemini-flash-lite-latest"
        )
        project_id = result.summary.project_id
        assert result.summary.status == ProjectStatus.WAITING_APPROVAL.value
        repo1.close()

        # Reopen: verify waiting_approval is still there
        repo2 = SqliteProjectRepository(db_path=db_path)
        repo2.initialize_schema()
        record = repo2.get(project_id)
        repo2.close()

        assert record is not None
        assert record.project.status == ProjectStatus.WAITING_APPROVAL
        assert len(record.approvals) > 0


class TestSqliteRepositoryAuditIntegrity:
    def test_approvals_persisted_with_correct_status(self, tmp_path):
        db_path = str(tmp_path / "audit_test.db")
        repo = SqliteProjectRepository(db_path=db_path)
        repo.initialize_schema()
        orchestrator = PMOrchestrator(repository=repo)

        brief = ProjectBrief(
            objective="Audit integrity test",
            raw_request="Check approval audit",
        )
        result = orchestrator.run(
            brief=brief, trend_provider_name="gemini-flash-lite-latest"
        )
        project_id = result.summary.project_id

        record = repo.get(project_id)
        assert len(record.approvals) > 0
        for approval in record.approvals:
            assert approval.action_type is not None
            assert approval.status is not None
        repo.close()

    def test_checkpoints_persisted(self, tmp_path):
        db_path = str(tmp_path / "checkpoint_test.db")
        repo = SqliteProjectRepository(db_path=db_path)
        repo.initialize_schema()
        orchestrator = PMOrchestrator(repository=repo)

        brief = ProjectBrief(
            objective="Checkpoint test",
            raw_request="Check checkpoint persistence",
        )
        orchestrator.run(
            brief=brief,
            trend_provider_name="gemini-flash-lite-latest",
        )
        # Run approval to create delivery checkpoint
        result2 = orchestrator.run(brief=brief, trend_provider_name="mock")
        project_id2 = result2.summary.project_id

        record = repo.get(project_id2)
        assert len(record.checkpoints) > 0
        repo.close()

    def test_save_overwrites_correctly(self, tmp_db):
        """Save twice: second save must reflect updated state."""
        orchestrator = PMOrchestrator(repository=tmp_db)
        brief = ProjectBrief(
            objective="Overwrite test",
            raw_request="Save should overwrite",
        )
        result = orchestrator.run(
            brief=brief, trend_provider_name="gemini-flash-lite-latest"
        )
        project_id = result.summary.project_id

        # Record before approval
        record_before = tmp_db.get(project_id)
        assert record_before.project.status == ProjectStatus.WAITING_APPROVAL

        # Approve
        from app.schemas.project import ActorContext, ActorRole, ActorType
        actor = ActorContext(
            actor_id="u-test",
            actor_role=ActorRole.APPROVER,
            actor_type=ActorType.HUMAN,
        )
        orchestrator.resume_from_approval(
            project_id=project_id,
            approved_actions=["external_api_send"],
            actor=actor,
            trend_provider_name="mock",
        )

        record_after = tmp_db.get(project_id)
        assert record_after.project.status == ProjectStatus.COMPLETED


class TestCreateRepositoryFromEnv:
    def test_sqlite_backend_from_env(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "env_test.db")
        monkeypatch.setenv("STATE_BACKEND", "sqlite")
        monkeypatch.setenv("SQLITE_DB_PATH", db_path)

        from app.state.repository import create_repository_from_env
        repo = create_repository_from_env()
        assert isinstance(repo, SqliteProjectRepository)
        repo.close()

    def test_sqlite3_alias_from_env(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "alias_test.db")
        monkeypatch.setenv("STATE_BACKEND", "sqlite3")
        monkeypatch.setenv("SQLITE_DB_PATH", db_path)

        from app.state.repository import create_repository_from_env
        repo = create_repository_from_env()
        assert isinstance(repo, SqliteProjectRepository)
        repo.close()

    def test_memory_backend_still_works(self, monkeypatch):
        monkeypatch.setenv("STATE_BACKEND", "memory")

        from app.state.repository import InMemoryProjectRepository, create_repository_from_env
        repo = create_repository_from_env()
        assert isinstance(repo, InMemoryProjectRepository)
