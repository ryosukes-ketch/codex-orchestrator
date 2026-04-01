from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import dependencies, main, routes, runtime_bindings
from app.schemas.project import ActorContext, ActorRole, ActorType
from app.services.auth import AuthenticationError


def _request_with_optional_state_auth(auth_service=...):
    state = SimpleNamespace()
    if auth_service is not ...:
        state.auth_service = auth_service
    return SimpleNamespace(app=SimpleNamespace(state=state))


def test_create_app_includes_router_and_metadata() -> None:
    app = main.create_app()

    assert app.title == "AI Work System Scaffold"
    assert app.version == "0.1.0"
    assert app._initial_orchestrator is app.state.orchestrator
    assert app._bootstrap_orchestrator is app.state.orchestrator
    assert app.state._initial_orchestrator is app.state.orchestrator
    assert app.state._bootstrap_orchestrator is app.state.orchestrator
    assert app._initial_auth_service is app.state.auth_service
    assert app._bootstrap_auth_service is app.state.auth_service
    assert app.state.auth_service is app.state._initial_auth_service
    assert app.state._bootstrap_auth_service is app.state.auth_service

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_auth_service_dependency_is_cached(monkeypatch) -> None:
    marker = object()
    call_count = {"value": 0}

    def _fake_get_auth_service():
        call_count["value"] += 1
        return marker

    dependencies.get_auth_service_dependency.cache_clear()
    monkeypatch.setattr(dependencies, "get_auth_service", _fake_get_auth_service)

    request = _request_with_optional_state_auth()
    first = dependencies.get_auth_service_dependency(request)
    second = dependencies.get_auth_service_dependency(request)

    assert first is marker
    assert second is marker
    assert call_count["value"] == 1

    dependencies.get_auth_service_dependency.cache_clear()


def test_get_auth_service_dependency_prefers_request_app_state_service(monkeypatch) -> None:
    state_auth_service = object()
    request = _request_with_optional_state_auth(state_auth_service)

    dependencies.get_auth_service_dependency.cache_clear()

    def _fake_get_auth_service():
        raise AssertionError("cached fallback should not be called when app state has auth_service")

    monkeypatch.setattr(dependencies, "get_auth_service", _fake_get_auth_service)

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is state_auth_service
    assert request.app._initial_auth_service is state_auth_service
    assert request.app.state._initial_auth_service is state_auth_service

    dependencies.get_auth_service_dependency.cache_clear()


def test_get_auth_service_dependency_binds_fallback_to_request_state(monkeypatch) -> None:
    marker_one = object()
    marker_two = object()
    call_count = {"value": 0}

    def _fake_get_auth_service():
        call_count["value"] += 1
        if call_count["value"] == 1:
            return marker_one
        return marker_two

    dependencies.get_auth_service_dependency.cache_clear()
    monkeypatch.setattr(dependencies, "get_auth_service", _fake_get_auth_service)

    request = _request_with_optional_state_auth()
    first = dependencies.get_auth_service_dependency(request)
    assert first is marker_one
    assert request.app._initial_auth_service is marker_one
    assert request.app.state.auth_service is marker_one

    dependencies.get_auth_service_dependency.cache_clear()
    second = dependencies.get_auth_service_dependency(request)
    assert second is marker_one
    assert call_count["value"] == 1

    dependencies.get_auth_service_dependency.cache_clear()


def test_get_auth_service_dependency_without_request_state_uses_cache(
    monkeypatch,
) -> None:
    marker = object()
    call_count = {"value": 0}

    def _fake_get_auth_service():
        call_count["value"] += 1
        return marker

    dependencies.get_auth_service_dependency.cache_clear()
    monkeypatch.setattr(dependencies, "get_auth_service", _fake_get_auth_service)

    request = SimpleNamespace(app=SimpleNamespace())
    first = dependencies.get_auth_service_dependency(request)
    second = dependencies.get_auth_service_dependency(request)

    assert first is marker
    assert second is marker
    assert call_count["value"] == 1

    dependencies.get_auth_service_dependency.cache_clear()


def test_get_auth_service_dependency_restores_app_scoped_initial_service() -> None:
    state = SimpleNamespace(_initial_auth_service=object())
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is state._initial_auth_service
    assert state.auth_service is state._initial_auth_service


def test_get_auth_service_dependency_restores_from_app_snapshot_when_state_missing() -> None:
    app = SimpleNamespace(_initial_auth_service=object())
    request = SimpleNamespace(app=app)

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is app._initial_auth_service


def test_get_auth_service_dependency_restores_state_from_app_snapshot() -> None:
    app_initial_auth_service = object()
    state = SimpleNamespace()
    request = SimpleNamespace(
        app=SimpleNamespace(state=state, _initial_auth_service=app_initial_auth_service)
    )

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is app_initial_auth_service
    assert state.auth_service is app_initial_auth_service
    assert state._initial_auth_service is app_initial_auth_service


def test_get_auth_service_dependency_state_binding_overrides_stale_snapshots() -> None:
    state_auth_service = object()
    stale_auth_service = object()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                auth_service=state_auth_service,
                _initial_auth_service=stale_auth_service,
                _bootstrap_auth_service=stale_auth_service,
            ),
            _initial_auth_service=stale_auth_service,
        )
    )

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is state_auth_service
    assert request.app._initial_auth_service is state_auth_service
    assert request.app.state._initial_auth_service is state_auth_service
    assert request.app.state._bootstrap_auth_service is state_auth_service


def test_get_auth_service_dependency_restores_from_bootstrap_snapshot() -> None:
    bootstrap_auth_service = object()
    state = SimpleNamespace(_bootstrap_auth_service=bootstrap_auth_service)
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is bootstrap_auth_service
    assert request.app._initial_auth_service is bootstrap_auth_service
    assert request.app.state.auth_service is bootstrap_auth_service
    assert request.app.state._initial_auth_service is bootstrap_auth_service


def test_get_auth_service_dependency_prefers_app_snapshot_over_bootstrap_snapshot() -> None:
    app_initial_auth_service = object()
    bootstrap_auth_service = object()
    state = SimpleNamespace(_bootstrap_auth_service=bootstrap_auth_service)
    request = SimpleNamespace(
        app=SimpleNamespace(state=state, _initial_auth_service=app_initial_auth_service)
    )

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is app_initial_auth_service
    assert request.app.state.auth_service is app_initial_auth_service
    assert request.app.state._initial_auth_service is app_initial_auth_service
    assert request.app.state._bootstrap_auth_service is app_initial_auth_service


def test_get_auth_service_dependency_restores_from_app_bootstrap_when_primary_snapshots_missing(
) -> None:
    app_bootstrap_auth_service = object()
    state = SimpleNamespace()
    request = SimpleNamespace(
        app=SimpleNamespace(state=state, _bootstrap_auth_service=app_bootstrap_auth_service)
    )

    resolved = dependencies.get_auth_service_dependency(request)

    assert resolved is app_bootstrap_auth_service
    assert request.app._initial_auth_service is app_bootstrap_auth_service
    assert request.app.state.auth_service is app_bootstrap_auth_service
    assert request.app.state._initial_auth_service is app_bootstrap_auth_service
    assert request.app.state._bootstrap_auth_service is app_bootstrap_auth_service


def test_get_orchestrator_uses_state_binding_and_updates_app_snapshot() -> None:
    state_orchestrator = object()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(orchestrator=state_orchestrator))
    )

    resolved = routes._get_orchestrator(request)

    assert resolved is state_orchestrator
    assert request.app._initial_orchestrator is state_orchestrator
    assert request.app.state._initial_orchestrator is state_orchestrator
    assert request.app.state._bootstrap_orchestrator is state_orchestrator


def test_get_orchestrator_restores_state_from_state_snapshot() -> None:
    state_initial_orchestrator = object()
    state = SimpleNamespace(_initial_orchestrator=state_initial_orchestrator)
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    resolved = routes._get_orchestrator(request)

    assert resolved is state_initial_orchestrator
    assert state.orchestrator is state_initial_orchestrator
    assert request.app._initial_orchestrator is state_initial_orchestrator


def test_get_orchestrator_restores_state_from_app_snapshot() -> None:
    app_initial_orchestrator = object()
    state = SimpleNamespace()
    request = SimpleNamespace(
        app=SimpleNamespace(state=state, _initial_orchestrator=app_initial_orchestrator)
    )

    resolved = routes._get_orchestrator(request)

    assert resolved is app_initial_orchestrator
    assert state.orchestrator is app_initial_orchestrator
    assert state._initial_orchestrator is app_initial_orchestrator


def test_get_orchestrator_restores_from_bootstrap_snapshot() -> None:
    bootstrap_orchestrator = object()
    state = SimpleNamespace(_bootstrap_orchestrator=bootstrap_orchestrator)
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    resolved = routes._get_orchestrator(request)

    assert resolved is bootstrap_orchestrator
    assert request.app._initial_orchestrator is bootstrap_orchestrator
    assert request.app.state.orchestrator is bootstrap_orchestrator
    assert request.app.state._initial_orchestrator is bootstrap_orchestrator


def test_get_orchestrator_prefers_app_snapshot_over_bootstrap_snapshot() -> None:
    app_initial_orchestrator = object()
    bootstrap_orchestrator = object()
    state = SimpleNamespace(_bootstrap_orchestrator=bootstrap_orchestrator)
    request = SimpleNamespace(
        app=SimpleNamespace(state=state, _initial_orchestrator=app_initial_orchestrator)
    )

    resolved = routes._get_orchestrator(request)

    assert resolved is app_initial_orchestrator
    assert request.app.state.orchestrator is app_initial_orchestrator
    assert request.app.state._initial_orchestrator is app_initial_orchestrator
    assert request.app.state._bootstrap_orchestrator is app_initial_orchestrator


def test_get_orchestrator_restores_from_app_bootstrap_when_primary_snapshots_missing() -> None:
    app_bootstrap_orchestrator = object()
    state = SimpleNamespace()
    request = SimpleNamespace(
        app=SimpleNamespace(state=state, _bootstrap_orchestrator=app_bootstrap_orchestrator)
    )

    resolved = routes._get_orchestrator(request)

    assert resolved is app_bootstrap_orchestrator
    assert request.app._initial_orchestrator is app_bootstrap_orchestrator
    assert request.app.state.orchestrator is app_bootstrap_orchestrator
    assert request.app.state._initial_orchestrator is app_bootstrap_orchestrator
    assert request.app.state._bootstrap_orchestrator is app_bootstrap_orchestrator


def test_get_orchestrator_binds_global_fallback_to_app_when_snapshots_missing(monkeypatch) -> None:
    global_orchestrator = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    monkeypatch.setattr(routes, "orchestrator", global_orchestrator)

    resolved = routes._get_orchestrator(request)

    assert resolved is global_orchestrator
    assert request.app._initial_orchestrator is global_orchestrator
    assert request.app._bootstrap_orchestrator is global_orchestrator
    assert request.app.state.orchestrator is global_orchestrator
    assert request.app.state._initial_orchestrator is global_orchestrator
    assert request.app.state._bootstrap_orchestrator is global_orchestrator


def test_bind_auth_service_binding_sets_all_snapshots() -> None:
    auth_service = object()
    app = SimpleNamespace(state=SimpleNamespace())

    runtime_bindings.bind_auth_service_binding(app, auth_service=auth_service)

    assert app._initial_auth_service is auth_service
    assert app._bootstrap_auth_service is auth_service
    assert app.state.auth_service is auth_service
    assert app.state._initial_auth_service is auth_service
    assert app.state._bootstrap_auth_service is auth_service


def test_bind_orchestrator_binding_sets_all_snapshots() -> None:
    orchestrator = object()
    app = SimpleNamespace(state=SimpleNamespace())

    runtime_bindings.bind_orchestrator_binding(app, orchestrator=orchestrator)

    assert app._initial_orchestrator is orchestrator
    assert app._bootstrap_orchestrator is orchestrator
    assert app.state.orchestrator is orchestrator
    assert app.state._initial_orchestrator is orchestrator
    assert app.state._bootstrap_orchestrator is orchestrator


def test_clear_auth_service_dependency_caches_resets_dependency_and_auth_cache(
    monkeypatch,
) -> None:
    try:
        dependencies.clear_auth_service_dependency_caches()
        monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
        disabled = dependencies.get_auth_service_dependency(_request_with_optional_state_auth())
        assert disabled.enabled is False

        monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
        still_disabled = dependencies.get_auth_service_dependency(
            _request_with_optional_state_auth()
        )
        assert still_disabled.enabled is False

        dependencies.clear_auth_service_dependency_caches()
        enabled = dependencies.get_auth_service_dependency(_request_with_optional_state_auth())
        assert enabled.enabled is True
    finally:
        dependencies.clear_auth_service_dependency_caches()


def test_clear_auth_service_dependency_caches_tolerates_uncached_auth_loader(monkeypatch) -> None:
    dependencies.get_auth_service_dependency.cache_clear()
    monkeypatch.setattr(dependencies, "get_auth_service", lambda: object())

    dependencies.clear_auth_service_dependency_caches()


def test_resolve_authenticated_actor_records_success(monkeypatch) -> None:
    actor = ActorContext(
        actor_id="approver-1",
        actor_role=ActorRole.APPROVER,
        actor_type=ActorType.HUMAN,
    )

    class _AuthService:
        def resolve_actor(self, authorization: str | None):
            assert authorization == "Bearer valid-token"
            return actor

    class _Orchestrator:
        def __init__(self) -> None:
            self.success_calls: list[tuple[str, str]] = []
            self.failure_calls: list[tuple[str, str]] = []

        def record_authentication_success(self, project_id: str, actor: ActorContext) -> None:
            self.success_calls.append((project_id, actor.actor_id))

        def record_authentication_failure(self, project_id: str, reason: str) -> None:
            self.failure_calls.append((project_id, reason))

    orchestrator = _Orchestrator()
    monkeypatch.setattr(routes, "orchestrator", orchestrator)

    resolved = routes._resolve_authenticated_actor(
        auth_service=_AuthService(),
        authorization="Bearer valid-token",
        project_id="proj-1",
    )

    assert resolved == actor
    assert orchestrator.success_calls == [("proj-1", "approver-1")]
    assert orchestrator.failure_calls == []


def test_resolve_authenticated_actor_records_failure_and_raises_http_401(monkeypatch) -> None:
    class _AuthService:
        def resolve_actor(self, authorization: str | None):
            raise AuthenticationError("Invalid bearer token.")

    class _Orchestrator:
        def __init__(self) -> None:
            self.failure_calls: list[tuple[str, str]] = []

        def record_authentication_success(self, project_id: str, actor: ActorContext) -> None:
            raise AssertionError("should not be called")

        def record_authentication_failure(self, project_id: str, reason: str) -> None:
            self.failure_calls.append((project_id, reason))

    orchestrator = _Orchestrator()
    monkeypatch.setattr(routes, "orchestrator", orchestrator)

    try:
        routes._resolve_authenticated_actor(
            auth_service=_AuthService(),
            authorization="Bearer invalid-token",
            project_id="proj-2",
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Invalid bearer token."

    assert orchestrator.failure_calls == [("proj-2", "Invalid bearer token.")]


def test_run_with_authenticated_actor_returns_action_result(monkeypatch) -> None:
    actor = ActorContext(
        actor_id="approver-1",
        actor_role=ActorRole.APPROVER,
        actor_type=ActorType.HUMAN,
    )

    class _AuthService:
        def resolve_actor(self, authorization: str | None):
            assert authorization == "Bearer valid-token"
            return actor

    class _Orchestrator:
        def record_authentication_success(self, project_id: str, actor: ActorContext) -> None:
            return None

        def record_authentication_failure(self, project_id: str, reason: str) -> None:
            raise AssertionError("should not be called")

    monkeypatch.setattr(routes, "orchestrator", _Orchestrator())
    result = routes._run_with_authenticated_actor(
        project_id="proj-1",
        authorization="Bearer valid-token",
        auth_service=_AuthService(),
        action=lambda resolved_actor: {"actor_id": resolved_actor.actor_id},
    )

    assert result == {"actor_id": "approver-1"}


def test_run_with_authenticated_actor_maps_lookup_error_to_http_404(monkeypatch) -> None:
    actor = ActorContext(
        actor_id="approver-1",
        actor_role=ActorRole.APPROVER,
        actor_type=ActorType.HUMAN,
    )

    class _AuthService:
        def resolve_actor(self, authorization: str | None):
            return actor

    class _Orchestrator:
        def record_authentication_success(self, project_id: str, actor: ActorContext) -> None:
            return None

        def record_authentication_failure(self, project_id: str, reason: str) -> None:
            raise AssertionError("should not be called")

    monkeypatch.setattr(routes, "orchestrator", _Orchestrator())

    try:
        routes._run_with_authenticated_actor(
            project_id="proj-1",
            authorization="Bearer valid-token",
            auth_service=_AuthService(),
            action=lambda resolved_actor: (_ for _ in ()).throw(LookupError("missing project")),
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "missing project"


def test_run_with_authenticated_actor_preserves_http_401_from_auth_resolution(
    monkeypatch,
) -> None:
    class _AuthService:
        def resolve_actor(self, authorization: str | None):
            raise AuthenticationError("Invalid bearer token.")

    class _Orchestrator:
        def record_authentication_success(self, project_id: str, actor: ActorContext) -> None:
            raise AssertionError("should not be called")

        def record_authentication_failure(self, project_id: str, reason: str) -> None:
            return None

    monkeypatch.setattr(routes, "orchestrator", _Orchestrator())

    try:
        routes._run_with_authenticated_actor(
            project_id="proj-2",
            authorization="Bearer invalid-token",
            auth_service=_AuthService(),
            action=lambda resolved_actor: {"actor_id": resolved_actor.actor_id},
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Invalid bearer token."


def test_raise_route_http_error_maps_authentication_error_to_http_401() -> None:
    try:
        routes._raise_route_http_error(AuthenticationError("token invalid"))
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "token invalid"
