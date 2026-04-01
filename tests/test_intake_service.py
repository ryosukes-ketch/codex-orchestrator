from app.intake.service import IntakeAgent


def test_build_brief_preserves_normalized_request_and_parses_stakeholders() -> None:
    agent = IntakeAgent()
    request = (
        "\n  Title: Delivery Bridge\n"
        "Scope: adapter layer\n"
        "Constraints: python,  fastapi , \n"
        "Success Criteria: typed outputs, stable tests\n"
        "Deadline: 2026-05-30\n"
        "Stakeholders: alice, bob ,  carol\n"
    )

    result = agent.build_brief(request)

    assert result.brief.objective == request.strip()
    assert result.brief.raw_request == request.strip()
    assert result.brief.title == "Delivery Bridge"
    assert result.brief.scope == "adapter layer"
    assert result.brief.constraints == ["python", "fastapi"]
    assert result.brief.success_criteria == ["typed outputs", "stable tests"]
    assert result.brief.deadline == "2026-05-30"
    assert result.brief.stakeholders == ["alice", "bob", "carol"]


def test_build_brief_missing_fields_order_and_questions_are_stable() -> None:
    agent = IntakeAgent()
    result = agent.build_brief("Build an internal assistant.")

    assert result.missing_fields == ["scope", "success_criteria", "constraints", "deadline"]
    assert result.clarifying_questions == [
        "What is the scope boundary (in-scope and out-of-scope)?",
        "How will we measure success for this project?",
        "What key constraints should we respect (time, budget, policy, stack)?",
    ]


def test_build_brief_extracts_fields_case_insensitively() -> None:
    agent = IntakeAgent()
    result = agent.build_brief(
        "TITLE: Platform\n"
        "SCOPE: intake contracts\n"
        "CONSTRAINTS: python\n"
        "SUCCESS-CRITERIA: parity checks\n"
        "DEADLINE: 2026-06-15\n"
    )

    assert result.brief.title == "Platform"
    assert result.brief.scope == "intake contracts"
    assert result.brief.constraints == ["python"]
    assert result.brief.success_criteria == ["parity checks"]
    assert result.brief.deadline == "2026-06-15"
    assert result.missing_fields == []
    assert result.clarifying_questions == []


def test_build_brief_extracts_multiline_bullet_lists() -> None:
    agent = IntakeAgent()
    result = agent.build_brief(
        "Title: Platform\n"
        "Scope: intake contracts\n"
        "Constraints:\n"
        "- python\n"
        "- fastapi\n"
        "Success Criteria:\n"
        "1) parity checks\n"
        "2. regression stable\n"
        "Deadline: 2026-06-15\n"
        "Stakeholders:\n"
        "- alice\n"
        "- bob\n"
    )

    assert result.brief.constraints == ["python", "fastapi"]
    assert result.brief.success_criteria == ["parity checks", "regression stable"]
    assert result.brief.stakeholders == ["alice", "bob"]
    assert result.missing_fields == []


def test_build_brief_splits_inline_list_fields_by_comma_or_semicolon() -> None:
    agent = IntakeAgent()
    result = agent.build_brief(
        "Title: Platform\n"
        "Scope: intake contracts\n"
        "Constraints: python; fastapi, pydantic\n"
        "Success Criteria: parity checks; regression stable\n"
        "Deadline: 2026-06-15\n"
        "Stakeholders: alice; bob, carol\n"
    )

    assert result.brief.constraints == ["python", "fastapi", "pydantic"]
    assert result.brief.success_criteria == ["parity checks", "regression stable"]
    assert result.brief.stakeholders == ["alice", "bob", "carol"]


def test_build_brief_deduplicates_list_field_values_preserving_first_order() -> None:
    agent = IntakeAgent()
    result = agent.build_brief(
        "Title: Platform\n"
        "Scope: intake contracts\n"
        "Constraints: python, fastapi, python, fastapi\n"
        "Success Criteria:\n"
        "- parity checks\n"
        "- parity checks\n"
        "- regression stable\n"
        "Deadline: 2026-06-15\n"
        "Stakeholders: alice, bob, alice\n"
    )

    assert result.brief.constraints == ["python", "fastapi"]
    assert result.brief.success_criteria == ["parity checks", "regression stable"]
    assert result.brief.stakeholders == ["alice", "bob"]
