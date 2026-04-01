import re

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
    def build_brief(self, user_request: str) -> IntakeResult:
        normalized_request = self._normalize_user_request(user_request)

        title = self._extract_value(normalized_request, "title")
        scope = self._extract_value(normalized_request, "scope")
        constraints = self._extract_list_field(normalized_request, "constraints")
        success_criteria = self._extract_list_field(normalized_request, "success_criteria")
        deadline = self._extract_value(normalized_request, "deadline")
        stakeholders = self._extract_list_field(normalized_request, "stakeholders")

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

