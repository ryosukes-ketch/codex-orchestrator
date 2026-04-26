import json
import os
import re

from app.llm.base import LLMClient
from app.llm.factory import get_llm_client
from app.schemas.brief import IntakeResult, ProjectBrief

FIELD_QUESTIONS = {
    "scope": "What is the scope boundary (in-scope and out-of-scope)?",
    "success_criteria": "How will we measure success for this project?",
    "constraints": "What key constraints should we respect (time, budget, policy, stack)?",
    "deadline": "Is there a target deadline or milestone date?",
}

FIELD_PATTERNS = {
    "title": [r"title\s*:\s*([^\n]+)"],
    "scope": [r"scope\s*:\s*([^\n]+)"],
    "constraints": [r"constraints?\s*:\s*([^\n]+)"],
    "success_criteria": [r"success[\s_-]*criteria\s*:\s*([^\n]+)"],
    "deadline": [r"deadline\s*:\s*([^\n]+)"],
    "stakeholders": [r"stakeholders?\s*:\s*([^\n]+)"],
}

LIST_FIELD_HEADERS = {
    "constraints": r"constraints?",
    "success_criteria": r"success[\s_-]*criteria",
    "stakeholders": r"stakeholders?",
}


class IntakeAgent:
    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        use_llm: bool | None = None,
    ) -> None:
        if use_llm is None:
            use_llm = os.getenv("INTAKE_USE_LLM", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self._use_llm = use_llm
        if llm_client is not None:
            self._llm_client = llm_client
        elif self._use_llm:
            self._llm_client = self._build_llm_client_from_env()
        else:
            self._llm_client = None

    @staticmethod
    def _unique_preserve_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def _extract_value(self, text: str, field: str) -> str | None:
        for pattern in FIELD_PATTERNS.get(field, []):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _split_list_values(self, raw: str) -> list[str]:
        values = [value.strip() for value in re.split(r"[,;]", raw) if value.strip()]
        return self._unique_preserve_order(values)

    def _extract_multiline_list_values(self, text: str, field: str) -> list[str]:
        header_pattern = LIST_FIELD_HEADERS.get(field)
        if not header_pattern:
            return []
        match = re.search(
            (
                rf"{header_pattern}\s*:\s*(?:\r?\n)"
                r"(?P<body>(?:\s*(?:[-*]|\d+[.)])\s*[^\n]+(?:\r?\n|$))+)"
            ),
            text,
            re.IGNORECASE,
        )
        if not match:
            return []
        body = match.group("body")
        values: list[str] = []
        for line in body.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if cleaned:
                values.append(cleaned)
        return self._unique_preserve_order(values)

    def _extract_inline_list_values(self, text: str, field: str) -> list[str]:
        header_pattern = LIST_FIELD_HEADERS.get(field)
        if not header_pattern:
            return []
        match = re.search(
            rf"{header_pattern}\s*:[ \t]*([^\n]+)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return []
        return self._split_list_values(match.group(1).strip())

    def _extract_list_field(self, text: str, field: str) -> list[str]:
        inline_values = self._extract_inline_list_values(text, field)
        if inline_values:
            return inline_values
        return self._extract_multiline_list_values(text, field)

    @staticmethod
    def _normalize_user_request(user_request: str) -> str:
        return (
            user_request.replace("`r`n", "\n")
            .replace("`n", "\n")
            .replace("\r\n", "\n")
            .strip()
        )

    @staticmethod
    def _parse_model_spec(raw_model: str) -> tuple[str, str]:
        candidate = raw_model.strip()
        if not candidate or candidate.lower() == "mock":
            return ("mock", "")
        if "/" not in candidate:
            return ("mock", "")
        provider, model = candidate.split("/", 1)
        return (provider.strip().lower(), model.strip())

    def _build_llm_client_from_env(self) -> LLMClient:
        provider, model = self._parse_model_spec(
            os.getenv("INTAKE_MODEL", os.getenv("RESEARCH_MODEL", "mock"))
        )
        return get_llm_client(provider, model)

    @staticmethod
    def _coerce_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    def _coerce_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            coerced = [str(item).strip() for item in value if str(item).strip()]
            return self._unique_preserve_order(coerced)
        if isinstance(value, str):
            return self._split_list_values(value)
        return []

    @staticmethod
    def _extract_first_json_object(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return ""
        return text[start : end + 1]

    def _extract_fields_via_llm(self, normalized_request: str) -> dict[str, object]:
        if not self._use_llm or self._llm_client is None:
            return {}

        system_prompt = (
            "Extract project brief fields from user text and return strict JSON only. "
            "Output keys: title (string or empty), scope (string or empty), "
            "constraints (array of strings), success_criteria (array of strings), "
            "deadline (string or empty), stakeholders (array of strings)."
        )
        user_prompt = (
            "Return JSON only.\n"
            "If a field is absent, use empty string for scalar fields and [] for list fields.\n"
            "User request:\n"
            f"{normalized_request}"
        )
        try:
            raw = self._llm_client.complete(system_prompt, user_prompt)
        except Exception:
            return {}

        candidate = self._extract_first_json_object(raw.strip())
        if not candidate:
            return {}
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def build_brief(self, user_request: str) -> IntakeResult:
        normalized_request = self._normalize_user_request(user_request)

        title = self._extract_value(normalized_request, "title")
        scope = self._extract_value(normalized_request, "scope")
        constraints = self._extract_list_field(normalized_request, "constraints")
        success_criteria = self._extract_list_field(normalized_request, "success_criteria")
        deadline = self._extract_value(normalized_request, "deadline")
        stakeholders = self._extract_list_field(normalized_request, "stakeholders")

        llm_fields = self._extract_fields_via_llm(normalized_request)
        if not title:
            title = self._coerce_text(llm_fields.get("title"))
        if not scope:
            scope = self._coerce_text(llm_fields.get("scope"))
        if not constraints:
            constraints = self._coerce_list(llm_fields.get("constraints"))
        if not success_criteria:
            success_criteria = self._coerce_list(llm_fields.get("success_criteria"))
        if not deadline:
            deadline = self._coerce_text(llm_fields.get("deadline"))
        if not stakeholders:
            stakeholders = self._coerce_list(llm_fields.get("stakeholders"))

        brief = ProjectBrief(
            title=title,
            objective=normalized_request,
            scope=scope,
            constraints=constraints,
            success_criteria=success_criteria,
            deadline=deadline,
            stakeholders=stakeholders,
            assumptions=[
                "Unspecified fields remain unset until user clarification.",
                "This brief is a draft and not final project approval.",
            ],
            raw_request=normalized_request,
        )

        missing_fields: list[str] = []
        if not brief.scope:
            missing_fields.append("scope")
        if not brief.success_criteria:
            missing_fields.append("success_criteria")
        if not brief.constraints:
            missing_fields.append("constraints")
        if not brief.deadline:
            missing_fields.append("deadline")

        clarifying_questions = [FIELD_QUESTIONS[field] for field in missing_fields[:3]]
        return IntakeResult(
            brief=brief,
            missing_fields=missing_fields,
            clarifying_questions=clarifying_questions,
        )
