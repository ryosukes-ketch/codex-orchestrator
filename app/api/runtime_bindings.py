from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

_T = TypeVar("_T")
_AuthServiceT = TypeVar("_AuthServiceT")
_OrchestratorT = TypeVar("_OrchestratorT")


@dataclass(frozen=True)
class _BindingSpec:
    state_binding_attr: str
    state_initial_attr: str
    app_initial_attr: str
    state_bootstrap_attr: str | None = None
    app_bootstrap_attr: str | None = None


_AUTH_BINDING_SPEC = _BindingSpec(
    state_binding_attr="auth_service",
    state_initial_attr="_initial_auth_service",
    state_bootstrap_attr="_bootstrap_auth_service",
    app_initial_attr="_initial_auth_service",
    app_bootstrap_attr="_bootstrap_auth_service",
)

_ORCHESTRATOR_BINDING_SPEC = _BindingSpec(
    state_binding_attr="orchestrator",
    state_initial_attr="_initial_orchestrator",
    state_bootstrap_attr="_bootstrap_orchestrator",
    app_initial_attr="_initial_orchestrator",
    app_bootstrap_attr="_bootstrap_orchestrator",
)


def bind_app_scoped_binding(
    app: object | None,
    *,
    binding: _T,
    state_binding_attr: str,
    state_initial_attr: str,
    app_initial_attr: str,
    state_bootstrap_attr: str | None = None,
    app_bootstrap_attr: str | None = None,
) -> None:
    app_state = getattr(app, "state", None)
    if app is not None:
        setattr(app, app_initial_attr, binding)
        if app_bootstrap_attr is not None:
            setattr(app, app_bootstrap_attr, binding)
    if app_state is None:
        return
    setattr(app_state, state_binding_attr, binding)
    setattr(app_state, state_initial_attr, binding)
    if state_bootstrap_attr is not None:
        setattr(app_state, state_bootstrap_attr, binding)


def resolve_app_scoped_binding(
    request: object | None,
    *,
    state_binding_attr: str,
    state_initial_attr: str,
    app_initial_attr: str,
    fallback_resolver: Callable[[], _T],
    state_bootstrap_attr: str | None = None,
    app_bootstrap_attr: str | None = None,
) -> _T:
    app = getattr(request, "app", None) if request is not None else None
    app_state = getattr(app, "state", None)

    def _sync_binding(binding: _T) -> _T:
        bind_app_scoped_binding(
            app,
            binding=binding,
            state_binding_attr=state_binding_attr,
            state_initial_attr=state_initial_attr,
            app_initial_attr=app_initial_attr,
            state_bootstrap_attr=state_bootstrap_attr,
            app_bootstrap_attr=app_bootstrap_attr,
        )
        return binding

    state_binding = getattr(app_state, state_binding_attr, None)
    if state_binding is not None:
        return _sync_binding(state_binding)

    state_initial = getattr(app_state, state_initial_attr, None)
    if state_initial is not None:
        return _sync_binding(state_initial)

    app_initial = getattr(app, app_initial_attr, None)
    if app_initial is not None:
        return _sync_binding(app_initial)

    if state_bootstrap_attr is not None:
        state_bootstrap = getattr(app_state, state_bootstrap_attr, None)
        if state_bootstrap is not None:
            return _sync_binding(state_bootstrap)

    if app_bootstrap_attr is not None:
        app_bootstrap = getattr(app, app_bootstrap_attr, None)
        if app_bootstrap is not None:
            return _sync_binding(app_bootstrap)

    resolved_binding = fallback_resolver()
    return _sync_binding(resolved_binding)


def _bind_binding_for_spec(
    app: object | None,
    *,
    binding: _T,
    spec: _BindingSpec,
) -> None:
    bind_app_scoped_binding(
        app,
        binding=binding,
        state_binding_attr=spec.state_binding_attr,
        state_initial_attr=spec.state_initial_attr,
        app_initial_attr=spec.app_initial_attr,
        state_bootstrap_attr=spec.state_bootstrap_attr,
        app_bootstrap_attr=spec.app_bootstrap_attr,
    )


def _resolve_binding_for_spec(
    request: object | None,
    *,
    spec: _BindingSpec,
    fallback_resolver: Callable[[], _T],
) -> _T:
    return resolve_app_scoped_binding(
        request,
        state_binding_attr=spec.state_binding_attr,
        state_initial_attr=spec.state_initial_attr,
        state_bootstrap_attr=spec.state_bootstrap_attr,
        app_initial_attr=spec.app_initial_attr,
        app_bootstrap_attr=spec.app_bootstrap_attr,
        fallback_resolver=fallback_resolver,
    )


def resolve_auth_service_binding(
    request: object | None,
    *,
    fallback_resolver: Callable[[], _AuthServiceT],
) -> _AuthServiceT:
    return _resolve_binding_for_spec(
        request,
        spec=_AUTH_BINDING_SPEC,
        fallback_resolver=fallback_resolver,
    )


def resolve_orchestrator_binding(
    request: object | None,
    *,
    fallback_resolver: Callable[[], _OrchestratorT],
) -> _OrchestratorT:
    return _resolve_binding_for_spec(
        request,
        spec=_ORCHESTRATOR_BINDING_SPEC,
        fallback_resolver=fallback_resolver,
    )


def bind_auth_service_binding(app: object | None, *, auth_service: _AuthServiceT) -> None:
    _bind_binding_for_spec(
        app,
        binding=auth_service,
        spec=_AUTH_BINDING_SPEC,
    )


def bind_orchestrator_binding(app: object | None, *, orchestrator: _OrchestratorT) -> None:
    _bind_binding_for_spec(
        app,
        binding=orchestrator,
        spec=_ORCHESTRATOR_BINDING_SPEC,
    )
