from app.intake.service import IntakeAgent


def test_intake_returns_max_three_questions() -> None:
    agent = IntakeAgent()
    result = agent.build_brief("Build a company-like AI work system.")

    assert len(result.clarifying_questions) <= 3
    assert "scope" in result.missing_fields
    assert "deadline" in result.missing_fields


def test_intake_extracts_structured_fields() -> None:
    agent = IntakeAgent()
    request = (
        "Title: Internal AI platform\n"
        "Scope: backend scaffold only\n"
        "Constraints: python, fastapi\n"
        "Success Criteria: testable api, clear docs\n"
        "Deadline: 2026-04-30"
    )
    result = agent.build_brief(request)

    assert result.brief.title == "Internal AI platform"
    assert result.brief.scope == "backend scaffold only"
    assert result.brief.deadline == "2026-04-30"
    assert result.brief.constraints == ["python", "fastapi"]
    assert result.brief.success_criteria == ["testable api", "clear docs"]
