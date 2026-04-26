import os

from app.llm.base import LLMClient
from app.llm.factory import get_llm_client
from app.llm.mock_client import MockLLMClient
from app.schemas.project import Department


def _parse_model_spec(spec: str) -> tuple[str, str]:
    """Parse 'provider/model-name' into (provider, model).

    Examples:
        'openai/gpt-4o-mini'       -> ('openai', 'gpt-4o-mini')
        'gemini/gemini-2.0-flash'  -> ('gemini', 'gemini-2.0-flash')
        'mock'                     -> ('mock', '')
        ''                         -> ('mock', '')
    """
    spec = spec.strip()
    if not spec or spec.lower() == "mock":
        return ("mock", "")
    parts = spec.split("/", 1)
    if len(parts) == 1:
        return ("mock", "")
    return (parts[0].lower(), parts[1])


_ENV_KEYS: dict[Department, str] = {
    Department.RESEARCH: "RESEARCH_MODEL",
    Department.DESIGN: "DESIGN_MODEL",
    Department.BUILD: "BUILD_MODEL",
    Department.REVIEW: "REVIEW_MODEL",
}


class DepartmentRegistry:
    """Maps each Department to an LLMClient.

    Build from environment variables with ``DepartmentRegistry.from_env()``.
    Individual departments can also be overridden for testing.
    """

    def __init__(self, clients: dict[Department, LLMClient] | None = None) -> None:
        self._clients: dict[Department, LLMClient] = clients or {}

    def get_client(self, department: Department) -> LLMClient:
        return self._clients.get(department, MockLLMClient())

    @classmethod
    def from_env(cls) -> "DepartmentRegistry":
        clients: dict[Department, LLMClient] = {}
        for dept, env_key in _ENV_KEYS.items():
            spec = os.environ.get(env_key, "mock")
            provider, model = _parse_model_spec(spec)
            clients[dept] = get_llm_client(provider, model)
        return cls(clients=clients)

    @classmethod
    def all_mock(cls) -> "DepartmentRegistry":
        """Convenience factory: all departments use MockLLMClient."""
        return cls(clients={dept: MockLLMClient() for dept in _ENV_KEYS})
