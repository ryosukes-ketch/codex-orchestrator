from app.schemas.project import ActorRole, ActorType
from app.services import auth
from app.services.auth import AuthenticationError, DevTokenAuthService


def test_parse_token_seed_uses_default_when_empty_or_invalid() -> None:
    default_map = auth._parse_token_seed(None)
    invalid_map = auth._parse_token_seed("bad-entry-format")

    assert "dev-owner-token" in default_map
    assert "dev-owner-token" in invalid_map


def test_parse_token_seed_parses_valid_entries() -> None:
    parsed = auth._parse_token_seed(
        "token-a:actor-a:approver:human,token-b:actor-b:admin:service"
    )

    assert parsed["token-a"].actor_id == "actor-a"
    assert parsed["token-a"].actor_role == ActorRole.APPROVER
    assert parsed["token-a"].actor_type == ActorType.HUMAN
    assert parsed["token-b"].actor_role == ActorRole.ADMIN
    assert parsed["token-b"].actor_type == ActorType.SERVICE


def test_parse_token_seed_skips_invalid_enum_entries_and_keeps_valid_entries() -> None:
    parsed = auth._parse_token_seed(
        "token-a:actor-a:approver:human,token-b:actor-b:not-a-role:human,token-c:actor-c:admin:service"
    )

    assert "token-a" in parsed
    assert "token-c" in parsed
    assert "token-b" not in parsed
    assert parsed["token-c"].actor_role == ActorRole.ADMIN
    assert parsed["token-c"].actor_type == ActorType.SERVICE


def test_parse_token_seed_strips_whitespace_from_fields() -> None:
    parsed = auth._parse_token_seed(" token-a : actor-a : approver : human ")

    assert parsed["token-a"].actor_id == "actor-a"
    assert parsed["token-a"].actor_role == ActorRole.APPROVER
    assert parsed["token-a"].actor_type == ActorType.HUMAN


def test_parse_token_seed_accepts_case_insensitive_role_and_type() -> None:
    parsed = auth._parse_token_seed("token-a:actor-a:APPROVER:HUMAN")

    assert parsed["token-a"].actor_id == "actor-a"
    assert parsed["token-a"].actor_role == ActorRole.APPROVER
    assert parsed["token-a"].actor_type == ActorType.HUMAN


def test_dev_token_auth_service_resolve_actor_success_and_failures() -> None:
    token_map = auth._parse_token_seed("token-a:actor-a:approver:human")
    service = DevTokenAuthService(token_map=token_map, enabled=True)

    actor = service.resolve_actor("Bearer token-a")
    assert actor.actor_id == "actor-a"
    assert actor.actor_role == ActorRole.APPROVER

    try:
        service.resolve_actor(None)
        raise AssertionError("expected AuthenticationError for missing header")
    except AuthenticationError as exc:
        assert "Missing Authorization header" in str(exc)

    try:
        service.resolve_actor("Basic token-a")
        raise AssertionError("expected AuthenticationError for invalid scheme")
    except AuthenticationError as exc:
        assert "Authorization must be Bearer token" in str(exc)

    try:
        service.resolve_actor("Bearer unknown")
        raise AssertionError("expected AuthenticationError for invalid token")
    except AuthenticationError as exc:
        assert "Invalid bearer token" in str(exc)


def test_dev_token_auth_service_resolve_actor_accepts_surrounding_whitespace() -> None:
    token_map = auth._parse_token_seed("token-a:actor-a:approver:human")
    service = DevTokenAuthService(token_map=token_map, enabled=True)

    actor = service.resolve_actor("   Bearer   token-a   ")

    assert actor.actor_id == "actor-a"
    assert actor.actor_role == ActorRole.APPROVER


def test_dev_token_auth_service_resolve_actor_accepts_case_insensitive_scheme_and_tabs() -> None:
    token_map = auth._parse_token_seed("token-a:actor-a:approver:human")
    service = DevTokenAuthService(token_map=token_map, enabled=True)

    actor = service.resolve_actor("bearer\t token-a")

    assert actor.actor_id == "actor-a"
    assert actor.actor_role == ActorRole.APPROVER


def test_dev_token_auth_service_disabled_returns_system_actor() -> None:
    service = DevTokenAuthService(token_map={}, enabled=False)

    actor = service.resolve_actor(None)

    assert actor.actor_id == "auth-disabled"
    assert actor.actor_role == ActorRole.ADMIN
    assert actor.actor_type == ActorType.SYSTEM


def test_get_auth_service_reads_env_after_cache_clear(monkeypatch) -> None:
    try:
        auth.get_auth_service.cache_clear()
        monkeypatch.setenv("DEV_AUTH_ENABLED", "false")
        monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "token-x:actor-x:admin:human")

        disabled_service = auth.get_auth_service()
        assert disabled_service.enabled is False

        auth.get_auth_service.cache_clear()
        monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
        monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "token-y:actor-y:viewer:human")

        enabled_service = auth.get_auth_service()
        assert enabled_service.enabled is True
        assert "token-y" in enabled_service.token_map
        assert enabled_service.token_map["token-y"].actor_role == ActorRole.VIEWER
    finally:
        auth.get_auth_service.cache_clear()


def test_get_auth_service_treats_invalid_enabled_env_as_default_true(monkeypatch) -> None:
    try:
        auth.get_auth_service.cache_clear()
        monkeypatch.setenv("DEV_AUTH_ENABLED", "definitely-not-bool")

        service = auth.get_auth_service()
        assert service.enabled is True
    finally:
        auth.get_auth_service.cache_clear()


def test_parse_bool_with_default_honors_truthy_falsy_and_default() -> None:
    assert auth._parse_bool_with_default("true", default=False) is True
    assert auth._parse_bool_with_default("off", default=True) is False
    assert auth._parse_bool_with_default("unexpected", default=True) is True
    assert auth._parse_bool_with_default("unexpected", default=False) is False


def test_parse_token_seed_without_default_fallback_returns_empty_map() -> None:
    assert auth._parse_token_seed(None, fallback_to_default=False) == {}
    assert auth._parse_token_seed("invalid-entry", fallback_to_default=False) == {}


def test_get_auth_service_supports_commercial_token_mode_without_dev_defaults(
    monkeypatch,
    tmp_path,
) -> None:
    try:
        auth.get_auth_service.cache_clear()
        monkeypatch.setenv("AUTH_SERVICE_MODE", "commercial_token")
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("AUTH_TOKEN_STORE_PATH", str(tmp_path / "commercial-store.json"))
        monkeypatch.delenv("AUTH_TOKEN_SEED", raising=False)
        monkeypatch.setenv("DEV_AUTH_TOKEN_SEED", "dev-only-token:actor-dev:approver:human")

        service = auth.get_auth_service()
        assert isinstance(service, auth.CommercialTokenAuthService)
        assert service.enabled is True
        assert service.token_map == {}

        try:
            service.resolve_actor("Bearer dev-only-token")
            raise AssertionError("expected AuthenticationError for non-commercial token")
        except AuthenticationError as exc:
            assert "Invalid bearer token" in str(exc)
    finally:
        auth.get_auth_service.cache_clear()


def test_commercial_auth_seed_tokens_remain_available_when_store_has_other_tokens(
    monkeypatch,
    tmp_path,
) -> None:
    store_path = tmp_path / "commercial-token-store.json"
    store_path.write_text(
        (
            "{\n"
            '  "version": 1,\n'
            '  "updated_at": "2026-01-01T00:00:00Z",\n'
            '  "tokens": [\n'
            "    {\n"
            '      "token": "store-only-token",\n'
            '      "actor_id": "store-actor",\n'
            '      "actor_role": "approver",\n'
            '      "actor_type": "human",\n'
            '      "created_at": "2026-01-01T00:00:00Z",\n'
            '      "updated_at": "2026-01-01T00:00:00Z",\n'
            '      "description": "from-store"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    try:
        auth.get_auth_service.cache_clear()
        monkeypatch.setenv("AUTH_SERVICE_MODE", "commercial_token")
        monkeypatch.setenv("AUTH_ENABLED", "true")
        monkeypatch.setenv("AUTH_TOKEN_STORE_PATH", str(store_path))
        monkeypatch.setenv("AUTH_TOKEN_SEED", "seed-token:seed-actor:approver:human")

        service = auth.get_auth_service()
        assert isinstance(service, auth.CommercialTokenAuthService)

        seed_actor = service.resolve_actor("Bearer seed-token")
        store_actor = service.resolve_actor("Bearer store-only-token")
        assert seed_actor.actor_id == "seed-actor"
        assert store_actor.actor_id == "store-actor"
    finally:
        auth.get_auth_service.cache_clear()
