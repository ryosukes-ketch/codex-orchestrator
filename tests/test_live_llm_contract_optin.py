import json
import os

import pytest

from app.llm.openclaw_client import OpenClawLLMClient


def _is_enabled() -> bool:
    return os.getenv("RUN_LIVE_LLM_CONTRACT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@pytest.mark.skipif(
    not _is_enabled(),
    reason="Set RUN_LIVE_LLM_CONTRACT=1 to enable live gateway contract tests.",
)
def test_openclaw_live_contract_returns_json_object_text() -> None:
    base_url = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"

    client = OpenClawLLMClient(
        agent_id=os.getenv("OPENCLAW_AGENT_ID", "codex-orchestrator"),
        base_url=base_url,
        auth_token=os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip() or None,
        backend_model=os.getenv("OPENCLAW_BACKEND_MODEL", "").strip() or None,
        timeout=int(os.getenv("OPENCLAW_LIVE_CONTRACT_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("OPENCLAW_LIVE_CONTRACT_MAX_RETRIES", "1")),
        retry_backoff_seconds=float(
            os.getenv("OPENCLAW_LIVE_CONTRACT_RETRY_BACKOFF_SECONDS", "0.75")
        ),
    )

    text = client.complete(
        "Return strict JSON object only.",
        (
            'Return {"contract":"ok","path":"openclaw_live_contract"} '
            "as JSON object only."
        ),
    )
    payload = json.loads(text)
    assert payload["contract"] == "ok"
    assert payload["path"] == "openclaw_live_contract"

    metadata = client.pop_last_call_metadata()
    assert metadata.get("provider") == "openclaw"
    assert metadata.get("gateway_success") is True
