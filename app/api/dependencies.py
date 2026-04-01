from functools import lru_cache

from fastapi import Request

from app.api.runtime_bindings import resolve_auth_service_binding
from app.services.auth import DevTokenAuthService, get_auth_service


@lru_cache(maxsize=1)
def _get_cached_auth_service_dependency() -> DevTokenAuthService:
    return get_auth_service()


def get_auth_service_dependency(request: Request) -> DevTokenAuthService:
    return resolve_auth_service_binding(
        request,
        fallback_resolver=_get_cached_auth_service_dependency,
    )


# Backward-compatible cache helpers used by tests and maintenance utilities.
get_auth_service_dependency.cache_clear = _get_cached_auth_service_dependency.cache_clear  # type: ignore[attr-defined]


def clear_auth_service_dependency_caches() -> None:
    _get_cached_auth_service_dependency.cache_clear()
    auth_service_cache_clear = getattr(get_auth_service, "cache_clear", None)
    if callable(auth_service_cache_clear):
        auth_service_cache_clear()
