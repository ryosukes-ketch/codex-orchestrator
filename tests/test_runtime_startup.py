import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import clear_auth_service_dependency_caches
from app.api.main import create_app
from app.state import repository as repository_module
from app.state.repository import InMemoryProjectRepository


@pytest.fixture(autouse=True)
def _reset_auth_service_runtime() -> None:
    clear_auth_service_dependency_caches()
    yield
    clear_auth_service_dependency_caches()


def _intake_brief(client: TestClient) -> dict:
    response = client.post(
        "/intake/brief",
        json={
            "user_request": (
                "Title: Runtime startup\n"
                "Scope: auth and approval runtime checks\n"
                "Constraints: python, fastapi\n"
                "Success Criteria: deterministic protected-route behavior\n"
                "Deadline: 2026-07-01"
            )
        },
    )
    assert response.status_code == 200
    return response.json()["brief"]


def _run_waiting_project(client: TestClient) -> str:
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(client), "trend_provider": "gemini"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["summary"]["status"] == "waiting_approval"
    return payload["record"]["project"]["id"]


def test_runtime_startup_create_app_exposes_operational_routes() -> None:
    app = create_app()
    route_paths = {route.path for route in app.routes}

    assert "/health" in route_paths
    assert "/intake/brief" in route_paths
    assert "/orchestrator/run" in route_paths
    assert "/orchestrator/resume/approval" in route_paths
    assert "/orchestrator/approval/reject" in route_paths
    assert "/orchestrator/resume/revision" in route_paths
    assert "/orchestrator/replanning/start" in route_paths
    assert "/projects/{project_id}/audit" in route_paths


def test_runtime_auth_env_flip_requires_new_app_instance(monkeypatch) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    client_auth_enabled = TestClient(create_app())

    project_auth_on = _run_waiting_project(client_auth_enabled)
    resume_auth_on = client_auth_enabled.post(
        "/orchestrator/resume/approval",
        json={"project_id": project_auth_on, "approved_actions": ["external_api_send"]},
    )
    assert resume_auth_on.status_code == 401

    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    clear_auth_service_dependency_caches()
    project_still_app_scoped = _run_waiting_project(client_auth_enabled)
    resume_still_app_scoped = client_auth_enabled.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_still_app_scoped,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert resume_still_app_scoped.status_code == 401

    client_auth_disabled = TestClient(create_app())
    project_auth_off = _run_waiting_project(client_auth_disabled)
    resume_auth_off = client_auth_disabled.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_auth_off,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert resume_auth_off.status_code == 200


def test_runtime_custom_token_seed_applies_to_actor_resolution(monkeypatch) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "DEV_AUTH_TOKEN_SEED",
        "runtime-token:ops-user:approver:human",
    )
    client = TestClient(create_app())

    project_id = _run_waiting_project(client)
    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "actor": {
                "actor_id": "forged-user",
                "actor_role": "admin",
                "actor_type": "human",
            },
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer runtime-token"},
    )
    assert resumed.status_code == 200

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "ops-user"
        for event in payload["events"]
    )
    assert any(
        event["event_type"] == "approval_approved" and event["actor"] == "ops-user"
        for event in payload["events"]
    )


def test_create_app_reloads_auth_config_on_env_flip_without_manual_cache_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    client_auth_disabled = TestClient(create_app())
    project_auth_disabled = _run_waiting_project(client_auth_disabled)
    resume_auth_disabled = client_auth_disabled.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_auth_disabled,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert resume_auth_disabled.status_code == 200

    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    client_auth_enabled = TestClient(create_app())
    project_auth_enabled = _run_waiting_project(client_auth_enabled)
    resume_auth_enabled = client_auth_enabled.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_auth_enabled,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert resume_auth_enabled.status_code == 401


def test_create_app_reinitializes_orchestrator_backend_selection_from_current_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "memory")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")

    app = create_app()
    assert isinstance(app.state.orchestrator.repository, InMemoryProjectRepository)

    monkeypatch.setenv("STATE_BACKEND", "unsupported-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    with pytest.raises(ValueError, match="Unsupported STATE_BACKEND"):
        create_app()


def test_create_app_restores_orchestrator_from_state_snapshot_when_app_snapshot_missing() -> None:
    app = create_app()
    client = TestClient(app)
    project_id = _run_waiting_project(client)
    delattr(app.state, "orchestrator")
    delattr(app, "_initial_orchestrator")

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    assert app.state.orchestrator is app.state._initial_orchestrator
    assert app._initial_orchestrator is app.state.orchestrator


def test_create_app_recovers_auth_and_orchestrator_from_state_snapshots_after_binding_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-startup:approver-startup:approver:human")
    app = create_app()
    client = TestClient(app)
    project_id = _run_waiting_project(client)
    delattr(app.state, "auth_service")
    delattr(app.state, "orchestrator")
    delattr(app, "_initial_auth_service")
    delattr(app, "_initial_orchestrator")

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-startup"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"
    assert app.state.auth_service is app.state._initial_auth_service
    assert app._initial_auth_service is app.state.auth_service
    assert app.state.orchestrator is app.state._initial_orchestrator
    assert app._initial_orchestrator is app.state.orchestrator


def test_create_app_recovers_from_bootstrap_snapshots_after_primary_bindings_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-bootstrap:approver-bootstrap:approver:human")
    app = create_app()
    client = TestClient(app)
    project_id = _run_waiting_project(client)

    for attr in ("auth_service", "_initial_auth_service", "orchestrator", "_initial_orchestrator"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    for attr in ("_initial_auth_service", "_initial_orchestrator"):
        if hasattr(app, attr):
            delattr(app, attr)

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-bootstrap"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"
    assert app.state.auth_service is app.state._bootstrap_auth_service
    assert app.state._initial_auth_service is app.state._bootstrap_auth_service
    assert app._initial_auth_service is app.state._bootstrap_auth_service
    assert app.state.orchestrator is app.state._bootstrap_orchestrator
    assert app.state._initial_orchestrator is app.state._bootstrap_orchestrator
    assert app._initial_orchestrator is app.state._bootstrap_orchestrator


def test_create_app_recovers_from_app_bootstrap_snapshots_when_state_bootstrap_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "DEV_AUTH_TOKEN_SEED",
        "seed-app-bootstrap:approver-bootstrap:approver:human",
    )
    app = create_app()
    client = TestClient(app)
    project_id = _run_waiting_project(client)

    for attr in (
        "auth_service",
        "_initial_auth_service",
        "_bootstrap_auth_service",
        "orchestrator",
        "_initial_orchestrator",
        "_bootstrap_orchestrator",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    for attr in ("_initial_auth_service", "_initial_orchestrator"):
        if hasattr(app, attr):
            delattr(app, attr)

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-app-bootstrap"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"
    assert app.state.auth_service is app._bootstrap_auth_service
    assert app.state._initial_auth_service is app._bootstrap_auth_service
    assert app.state._bootstrap_auth_service is app._bootstrap_auth_service
    assert app._initial_auth_service is app._bootstrap_auth_service
    assert app.state.orchestrator is app._bootstrap_orchestrator
    assert app.state._initial_orchestrator is app._bootstrap_orchestrator
    assert app.state._bootstrap_orchestrator is app._bootstrap_orchestrator
    assert app._initial_orchestrator is app._bootstrap_orchestrator


def test_create_app_backend_selection_respects_malformed_and_false_strict_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "unsupported-backend")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")

    app_non_strict = create_app()
    assert isinstance(app_non_strict.state.orchestrator.repository, InMemoryProjectRepository)

    monkeypatch.setenv("STATE_BACKEND_STRICT", "not-a-bool")
    with pytest.raises(ValueError, match="Unsupported STATE_BACKEND"):
        create_app()


def test_create_app_reinitializes_in_memory_repository_state_between_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "memory")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")

    first_client = TestClient(create_app())
    project_id = _run_waiting_project(first_client)
    first_audit = first_client.get(f"/projects/{project_id}/audit")
    assert first_audit.status_code == 200

    second_client = TestClient(create_app())
    first_audit_after_second_init = first_client.get(f"/projects/{project_id}/audit")
    assert first_audit_after_second_init.status_code == 200

    second_audit = second_client.get(f"/projects/{project_id}/audit")
    assert second_audit.status_code == 404


def test_create_app_treats_malformed_auth_enabled_as_secure_default_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "not-a-bool")

    client = TestClient(create_app())
    project_id = _run_waiting_project(client)
    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert resumed.status_code == 401


def test_create_app_treats_malformed_provider_strict_flag_as_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "not-a-bool")

    client = TestClient(create_app())
    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(client), "trend_provider": "unknown-provider"},
    )

    assert run.status_code == 409
    assert run.json()["detail"] == "Unsupported trend provider: unknown-provider"


def test_create_app_reloads_auth_token_seed_between_initializations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-a:approver-a:approver:human")

    first_client = TestClient(create_app())
    first_project_id = _run_waiting_project(first_client)
    first_resume = first_client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": first_project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-a"},
    )
    assert first_resume.status_code == 200

    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-b:approver-b:approver:human")
    second_client = TestClient(create_app())
    second_project_id = _run_waiting_project(second_client)

    stale_resume = second_client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": second_project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-a"},
    )
    assert stale_resume.status_code == 401

    fresh_resume = second_client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": second_project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-b"},
    )
    assert fresh_resume.status_code == 200


def test_create_app_postgres_without_dsn_non_strict_starts_with_memory_and_routes_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")

    app = create_app()
    assert isinstance(app.state.orchestrator.repository, InMemoryProjectRepository)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    run = client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(client), "trend_provider": "mock"},
    )
    assert run.status_code == 200
    assert run.json()["summary"]["status"] == "completed"


def test_create_app_malformed_backend_strict_then_corrected_env_recovers_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("STATE_BACKEND_STRICT", "not-a-bool")

    with pytest.raises(ValueError, match="requires DATABASE_URL"):
        create_app()

    monkeypatch.setenv("STATE_BACKEND", "memory")
    monkeypatch.delenv("STATE_BACKEND_STRICT", raising=False)
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"


def test_create_app_malformed_provider_strict_then_corrected_env_changes_run_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TREND_PROVIDER_STRICT", "not-a-bool")
    strict_client = TestClient(create_app())
    strict_run = strict_client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(strict_client), "trend_provider": "unknown-provider"},
    )
    assert strict_run.status_code == 409
    assert strict_run.json()["detail"] == "Unsupported trend provider: unknown-provider"

    monkeypatch.setenv("TREND_PROVIDER_STRICT", "false")
    non_strict_client = TestClient(create_app())
    non_strict_run = non_strict_client.post(
        "/orchestrator/run",
        json={"brief": _intake_brief(non_strict_client), "trend_provider": "unknown-provider"},
    )
    assert non_strict_run.status_code == 200
    assert non_strict_run.json()["summary"]["status"] == "completed"


def test_create_app_auth_disabled_allows_invalid_token_and_records_system_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    client = TestClient(create_app())
    project_id = _run_waiting_project(client)

    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "auth-disabled"
        for event in payload["events"]
    )
    assert any(
        event["event_type"] == "approval_approved" and event["actor"] == "auth-disabled"
        for event in payload["events"]
    )


def test_multiple_apps_keep_auth_enabled_setting_isolated_after_env_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
    app_auth_disabled = create_app()
    client_auth_disabled = TestClient(app_auth_disabled)
    project_auth_disabled = _run_waiting_project(client_auth_disabled)

    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    app_auth_enabled = create_app()
    client_auth_enabled = TestClient(app_auth_enabled)
    project_auth_enabled = _run_waiting_project(client_auth_enabled)

    disabled_resume = client_auth_disabled.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_auth_disabled,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )
    enabled_resume = client_auth_enabled.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_auth_enabled,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
    )

    assert disabled_resume.status_code == 200
    assert enabled_resume.status_code == 401


def test_multiple_apps_keep_token_seed_isolated_after_env_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-one:approver-one:approver:human")
    app_seed_one = create_app()
    client_seed_one = TestClient(app_seed_one)
    project_seed_one = _run_waiting_project(client_seed_one)

    monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "seed-two:approver-two:approver:human")
    app_seed_two = create_app()
    client_seed_two = TestClient(app_seed_two)
    project_seed_two = _run_waiting_project(client_seed_two)

    first_app_with_seed_one = client_seed_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_seed_one,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-one"},
    )
    first_app_with_seed_two = client_seed_one.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_seed_one,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-two"},
    )
    second_app_with_seed_two = client_seed_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_seed_two,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-two"},
    )
    second_app_with_seed_one = client_seed_two.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_seed_two,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer seed-one"},
    )

    assert first_app_with_seed_one.status_code == 200
    assert first_app_with_seed_two.status_code == 401
    assert second_app_with_seed_two.status_code == 200
    assert second_app_with_seed_one.status_code == 401


def test_create_app_falls_back_to_memory_when_postgres_init_fails_non_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("postgres unavailable at startup")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://startup-test")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FailingPostgresRepository)

    app = create_app()
    assert isinstance(app.state.orchestrator.repository, InMemoryProjectRepository)


def test_create_app_non_strict_postgres_init_failure_still_allows_manual_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("postgres unavailable at startup")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://startup-test")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "false")
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FailingPostgresRepository)

    client = TestClient(create_app())
    project_id = _run_waiting_project(client)
    resumed = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "trend_provider": "gemini",
        },
        headers={"Authorization": "Bearer dev-approver-token"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["summary"]["status"] == "completed"


def test_create_app_raises_when_postgres_init_fails_in_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def initialize_schema(self) -> None:
            raise RuntimeError("postgres unavailable at startup")

    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://startup-test")
    monkeypatch.setenv("STATE_BACKEND_STRICT", "true")
    monkeypatch.setattr(repository_module, "PostgresProjectRepository", _FailingPostgresRepository)

    with pytest.raises(RuntimeError, match="postgres unavailable at startup"):
        create_app()
