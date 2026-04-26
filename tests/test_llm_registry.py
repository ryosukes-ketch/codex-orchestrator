from app.llm.factory import get_llm_client
from app.llm.mock_client import MockLLMClient
from app.llm.registry import DepartmentRegistry, _parse_model_spec
from app.schemas.project import Department


def test_parse_model_spec_empty_returns_mock() -> None:
    assert _parse_model_spec("") == ("mock", "")


def test_parse_model_spec_mock_returns_mock() -> None:
    assert _parse_model_spec("mock") == ("mock", "")


def test_parse_model_spec_valid_provider_and_model() -> None:
    assert _parse_model_spec("openai/gpt-4o-mini") == ("openai", "gpt-4o-mini")


def test_parse_model_spec_gemini() -> None:
    assert _parse_model_spec("gemini/gemini-2.0-flash") == ("gemini", "gemini-2.0-flash")


def test_parse_model_spec_no_slash_falls_back_to_mock() -> None:
    assert _parse_model_spec("gpt-4o-mini") == ("mock", "")


def test_department_registry_all_mock_returns_mock_clients() -> None:
    registry = DepartmentRegistry.all_mock()
    for dept in (Department.RESEARCH, Department.DESIGN, Department.BUILD, Department.REVIEW):
        client = registry.get_client(dept)
        assert isinstance(client, MockLLMClient)


def test_department_registry_get_client_unknown_dept_returns_mock() -> None:
    registry = DepartmentRegistry()
    client = registry.get_client(Department.RESEARCH)
    assert isinstance(client, MockLLMClient)


def test_department_registry_from_env_uses_mock_when_unset(monkeypatch) -> None:
    for key in ("RESEARCH_MODEL", "DESIGN_MODEL", "BUILD_MODEL", "REVIEW_MODEL"):
        monkeypatch.setenv(key, "mock")
    registry = DepartmentRegistry.from_env()
    for dept in (Department.RESEARCH, Department.DESIGN, Department.BUILD, Department.REVIEW):
        assert isinstance(registry.get_client(dept), MockLLMClient)


def test_department_registry_from_env_falls_back_to_mock_when_api_key_missing(monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    registry = DepartmentRegistry.from_env()
    assert isinstance(registry.get_client(Department.RESEARCH), MockLLMClient)


def test_department_registry_custom_client() -> None:
    custom = MockLLMClient(fixed_response='{"result": "custom"}')
    registry = DepartmentRegistry(clients={Department.RESEARCH: custom})
    assert registry.get_client(Department.RESEARCH) is custom
    assert isinstance(registry.get_client(Department.DESIGN), MockLLMClient)


def test_parse_model_spec_openclaw() -> None:
    assert _parse_model_spec("openclaw/default") == ("openclaw", "default")


def test_department_registry_from_env_openclaw_creates_openclaw_client(monkeypatch) -> None:
    """When RESEARCH_MODEL=openclaw/default, an OpenClawLLMClient should be returned."""
    monkeypatch.setenv("RESEARCH_MODEL", "openclaw/default")
    from app.llm.openclaw_client import OpenClawLLMClient
    registry = DepartmentRegistry.from_env()
    client = registry.get_client(Department.RESEARCH)
    assert isinstance(client, OpenClawLLMClient)


def test_get_llm_client_openclaw_uses_gateway_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_BASE_URL", "http://127.0.0.1:28789/v1")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "token-1")
    monkeypatch.setenv("OPENCLAW_BACKEND_MODEL", "openai-codex/gpt-5.2")

    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "research")
    assert isinstance(client, OpenClawLLMClient)
    assert client._base_url == "http://127.0.0.1:28789/v1"
    assert client._auth_token == "token-1"
    assert client._backend_model == "openai-codex/gpt-5.2"
    assert client._agent_id == "research"


def test_get_llm_client_openclaw_inline_backend_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_BACKEND_MODEL", "openai-codex/gpt-5.2")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default@openai-codex/gpt-5.4")
    assert isinstance(client, OpenClawLLMClient)
    assert client._agent_id == "default"
    assert client._backend_model == "openai-codex/gpt-5.4"


def test_get_llm_client_openclaw_loads_token_from_config_when_env_missing(
    monkeypatch, tmp_path
) -> None:
    config = tmp_path / "openclaw.json"
    config.write_text(
        '{"gateway":{"auth":{"token":"config-token-123"}}}',
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("OPENCLAW_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))

    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._auth_token == "config-token-123"


def test_get_llm_client_openclaw_loads_token_from_json5_like_config_when_env_missing(
    monkeypatch, tmp_path
) -> None:
    config = tmp_path / "openclaw.json"
    config.write_text(
        """
        {
          gateway: {
            auth: {
              token: "json5-token-456",
            },
          },
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("OPENCLAW_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))

    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._auth_token == "json5-token-456"


def test_get_llm_client_openclaw_timeout_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_TIMEOUT_SECONDS", "13")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._timeout == 13


def test_get_llm_client_openclaw_retry_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_MAX_RETRIES", "3")
    monkeypatch.setenv("OPENCLAW_RETRY_BACKOFF_SECONDS", "1.25")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._max_retries == 3
    assert client._retry_backoff_seconds == 1.25


def test_get_llm_client_openclaw_chat_failure_cooldown_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS", "45")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._chat_failure_cooldown_seconds == 45.0


def test_get_llm_client_openclaw_invalid_timeout_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_TIMEOUT_SECONDS", "abc")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._timeout == 60


def test_get_llm_client_openclaw_invalid_retry_settings_use_defaults(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_MAX_RETRIES", "abc")
    monkeypatch.setenv("OPENCLAW_RETRY_BACKOFF_SECONDS", "abc")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._max_retries == 1
    assert client._retry_backoff_seconds == 0.75


def test_get_llm_client_openclaw_invalid_chat_failure_cooldown_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS", "abc")
    from app.llm.openclaw_client import OpenClawLLMClient

    client = get_llm_client("openclaw", "default")
    assert isinstance(client, OpenClawLLMClient)
    assert client._chat_failure_cooldown_seconds == 120.0
