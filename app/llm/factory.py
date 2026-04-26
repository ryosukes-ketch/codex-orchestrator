import os
import re
from json import JSONDecodeError, loads
from pathlib import Path

from app.llm.base import LLMClient
from app.llm.mock_client import MockLLMClient


def _parse_openclaw_model_spec(spec: str) -> tuple[str, str | None]:
    """Parse OpenClaw model spec into (agent_id, backend_override).

    Supported forms:
        default
        research
        default@openai-codex/gpt-5.2
    """
    raw = spec.strip()
    if not raw:
        return ("default", None)
    if "@" not in raw:
        return (raw, None)
    agent_id, backend = raw.split("@", 1)
    agent = agent_id.strip() or "default"
    backend_model = backend.strip() or None
    return (agent, backend_model)


def _parse_positive_int_or_default(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if value <= 0:
        return default
    return value


def _parse_non_negative_int_or_default(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if value < 0:
        return default
    return value


def _parse_non_negative_float_or_default(raw: str | None, default: float) -> float:
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if value < 0:
        return default
    return value


def _load_openclaw_token_from_config() -> str | None:
    config_path = os.environ.get("OPENCLAW_CONFIG_PATH", "~/.openclaw/openclaw.json")
    path = Path(config_path).expanduser()
    if not path.exists():
        return None
    try:
        config_text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = loads(config_text)
    except JSONDecodeError:
        return _extract_openclaw_token_from_json5_like_text(config_text)
    gateway = parsed.get("gateway")
    if not isinstance(gateway, dict):
        return None
    auth = gateway.get("auth")
    if not isinstance(auth, dict):
        return None
    token = auth.get("token")
    if not isinstance(token, str):
        return None
    cleaned = token.strip()
    return cleaned or None


def _extract_openclaw_token_from_json5_like_text(config_text: str) -> str | None:
    """Best-effort token extraction for OpenClaw JSON5 config files.

    OpenClaw's default config format is JSON5; when strict JSON parsing fails,
    this fallback extracts gateway.auth.token using a constrained regex.
    """
    match = re.search(
        r'(?is)(?:"gateway"|gateway)\s*:\s*\{[\s\S]*?'
        r'(?:"auth"|auth)\s*:\s*\{[\s\S]*?'
        r'(?:"token"|token)\s*:\s*"([^"]+)"',
        config_text,
    )
    if match is None:
        return None
    token = match.group(1).strip()
    return token or None


def get_llm_client(provider: str, model: str) -> LLMClient:
    """Return a concrete LLMClient for the given provider and model.

    Falls back to MockLLMClient if the provider is unknown, 'mock', or the
    required API key is missing.
    """
    p = provider.lower().strip()

    if p in ("", "mock"):
        return MockLLMClient()

    if p == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return MockLLMClient()
        from app.llm.openai_client import OpenAILLMClient

        return OpenAILLMClient(api_key=api_key, model=model)

    if p in ("gemini", "google"):
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            return MockLLMClient()
        from app.llm.gemini_client import GeminiLLMClient

        return GeminiLLMClient(api_key=api_key, model=model)

    if p == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return MockLLMClient()
        from app.llm.anthropic_client import AnthropicLLMClient

        return AnthropicLLMClient(api_key=api_key, model=model)

    if p in ("grok", "xai"):
        api_key = os.environ.get("GROK_API_KEY", "")
        if not api_key:
            return MockLLMClient()
        from app.llm.grok_client import GrokLLMClient

        return GrokLLMClient(api_key=api_key, model=model)

    if p == "openclaw":
        # model field is used as agent_id:
        #   RESEARCH_MODEL=openclaw/default
        # Optional backend override:
        #   RESEARCH_MODEL=openclaw/default@openai-codex/gpt-5.2
        agent_id, inline_backend_override = _parse_openclaw_model_spec(model)
        base_url = os.environ.get("OPENCLAW_BASE_URL", "http://127.0.0.1:18789/v1")
        auth_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or os.environ.get(
            "OPENCLAW_AUTH_TOKEN"
        )
        if not auth_token:
            auth_token = _load_openclaw_token_from_config()
        backend_model = inline_backend_override or os.environ.get("OPENCLAW_BACKEND_MODEL")
        timeout_seconds = _parse_positive_int_or_default(
            os.environ.get("OPENCLAW_TIMEOUT_SECONDS"),
            default=60,
        )
        max_retries = _parse_non_negative_int_or_default(
            os.environ.get("OPENCLAW_MAX_RETRIES"),
            default=1,
        )
        retry_backoff_seconds = _parse_non_negative_float_or_default(
            os.environ.get("OPENCLAW_RETRY_BACKOFF_SECONDS"),
            default=0.75,
        )
        chat_failure_cooldown_seconds = _parse_non_negative_float_or_default(
            os.environ.get("OPENCLAW_CHAT_FAILURE_COOLDOWN_SECONDS"),
            default=120.0,
        )
        from app.llm.openclaw_client import OpenClawLLMClient

        return OpenClawLLMClient(
            agent_id=agent_id,
            base_url=base_url,
            auth_token=auth_token,
            backend_model=backend_model,
            timeout=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            chat_failure_cooldown_seconds=chat_failure_cooldown_seconds,
        )

    # Unknown provider — safe fallback
    return MockLLMClient()
