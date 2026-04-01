import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_json(path: str) -> dict:
    return json.loads(_read(path))


def test_readme_and_docs_markdown_local_references_exist() -> None:
    markdown_files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("**/*.md"))]
    reference_pattern = re.compile(
        r"`((?:docs|app|tests|\.env\.example|README\.md|AGENTS\.md|\.agents)"
        r"[^`\s]*\.(?:md|json|py|toml))`"
        r"|\((\.\.?/[^)\s]*\.(?:md|json|py|toml))\)"
    )

    missing: list[str] = []
    for file_path in markdown_files:
        content = file_path.read_text(encoding="utf-8")
        for match in reference_pattern.finditer(content):
            ref = match.group(1) or match.group(2)
            target = (
                (file_path.parent / ref).resolve()
                if ref.startswith("./") or ref.startswith("../")
                else ROOT / ref
            )
            if not target.exists():
                missing.append(f"{file_path.relative_to(ROOT)}::{ref}")

    assert missing == []


def test_decision_vocabulary_is_consistent_across_governance_docs() -> None:
    direction_guard = _load_json("docs/direction_guard.json")
    runbook = _read("docs/codex_continuation_runbook.md")
    prompts = _read("docs/codex_automation_prompts.md")
    readme = _read("README.md")

    assert set(direction_guard["decision_values"]) == {"GO", "PAUSE", "REVIEW"}
    assert "GO / PAUSE / REVIEW" in runbook
    assert "GO / PAUSE / REVIEW" in prompts
    assert "`GO`" in readme and "`PAUSE`" in readme and "`REVIEW`" in readme


def test_templates_and_examples_keep_expected_core_fields() -> None:
    brief_template = _load_json("docs/current_brief_template.json")
    work_order_template = _load_json("docs/current_work_order_template.json")
    review_packet_example = _load_json("docs/examples/management_review_packet_example.json")
    queue_item_example = _load_json("docs/examples/review_queue_item_example.json")
    decision_example = _load_json("docs/examples/management_decision_example.json")

    for key in ("brief_id", "project_id", "current_task", "risk_snapshot", "proposed_action"):
        assert key in brief_template
    for key in ("work_order_id", "project_id", "assigned_department", "governance", "verification"):
        assert key in work_order_template
    for key in ("packet_id", "project_id", "recommendation", "required_review"):
        assert key in review_packet_example
    for key in ("item_id", "related_project_id", "recommendation", "review_status"):
        assert key in queue_item_example
    for key in ("item_id", "decision", "reviewer_id", "rationale"):
        assert key in decision_example


def test_readme_and_runbooks_reference_existing_support_artifacts() -> None:
    readme = _read("README.md")
    runbook = _read("docs/codex_continuation_runbook.md")
    prompts = _read("docs/codex_automation_prompts.md")

    assert "docs/codex_continuation_runbook.md" in readme
    assert "docs/codex_automation_prompts.md" in readme
    assert "docs/model_governance_policy.md" in readme
    assert "docs/model_routing_policy.json" in readme
    assert "docs/staging_validation_plan.md" in readme
    assert "docs/staging_execution_record.md" in readme
    assert "docs/staging_evidence_template.md" in readme
    assert "docs/staging_issue_triage_template.md" in readme
    assert "docs/staging_signoff_template.md" in readme
    assert "docs/live_validation_checklist.md" in readme
    assert "docs/rollout_plan.md" in readme
    assert "docs/rollback_checklist.md" in readme
    assert "docs/production_readiness_gaps.md" in readme
    assert "docs/system_requirements.md" in readme
    assert "docs/mvp_requirements.md" in readme
    assert "docs/pre_production_requirements.md" in readme
    assert "docs/non_goals.md" in readme
    assert "docs/requirement_traceability_matrix.md" in readme
    assert "docs/acceptance_criteria.md" in readme
    assert "docs/direction_guard.json" in runbook
    assert "docs/roadmap.json" in runbook
    assert "$continue-workflow" in prompts


def test_requirements_package_docs_exist_and_traceability_mentions_core_artifacts() -> None:
    required_docs = [
        "docs/system_requirements.md",
        "docs/mvp_requirements.md",
        "docs/pre_production_requirements.md",
        "docs/non_goals.md",
        "docs/requirement_traceability_matrix.md",
        "docs/acceptance_criteria.md",
    ]
    for path in required_docs:
        assert (ROOT / path).exists(), path

    traceability = _read("docs/requirement_traceability_matrix.md")
    expected_artifact_terms = [
        "current brief",
        "triage result",
        "trend report",
        "work order",
        "management summary",
        "projected activation decision",
        "approval record",
        "handoff envelope",
    ]
    for term in expected_artifact_terms:
        assert term in traceability, term

    acceptance = _read("docs/acceptance_criteria.md")
    assert "AC-1 Code and logic readiness (offline)" in acceptance
    assert "AC-2 Offline operational readiness" in acceptance
    assert "AC-3 Staging entry criteria" in acceptance
    assert "AC-4 Live validation entry criteria" in acceptance


def test_staging_execution_support_docs_exist_and_include_expected_sections() -> None:
    execution_record = _read("docs/staging_execution_record.md")
    evidence = _read("docs/staging_evidence_template.md")
    triage = _read("docs/staging_issue_triage_template.md")
    signoff = _read("docs/staging_signoff_template.md")

    for path in (
        "docs/staging_execution_record.md",
        "docs/staging_evidence_template.md",
        "docs/staging_issue_triage_template.md",
        "docs/staging_signoff_template.md",
    ):
        assert (ROOT / path).exists(), path

    assert "## Step-by-step log" in execution_record
    assert "## Final staging recommendation" in execution_record

    for heading in (
        "### 1. Startup",
        "### 2. Auth",
        "### 3. Provider",
        "### 4. Persistence",
        "### 5. Manual workflow",
        "### 6. Rollback",
    ):
        assert heading in evidence

    assert "- Severity: P0 / P1 / P2 / P3" in triage
    assert "## Go/No-Go effect" in triage

    assert "### Auth signoff" in signoff
    assert "### Provider signoff" in signoff
    assert "### Persistence signoff" in signoff
    assert "### Rollback signoff" in signoff
    assert "## Final release decision" in signoff


def test_env_example_uses_placeholders_and_expected_keys() -> None:
    env_text = _read(".env.example")
    required_keys = {
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GROK_API_KEY",
        "STATE_BACKEND",
        "DATABASE_URL",
        "STATE_BACKEND_STRICT",
        "TREND_PROVIDER_STRICT",
        "DEV_AUTH_ENABLED",
        "DEV_AUTH_TOKEN_SEED",
        "TEST_DATABASE_URL",
    }
    parsed = {}
    for line in env_text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()

    assert required_keys.issubset(set(parsed))
    assert parsed["OPENAI_API_KEY"] == "your_openai_api_key_here"
    assert parsed["GEMINI_API_KEY"] == "your_gemini_api_key_here"
    assert parsed["GROK_API_KEY"] == "your_grok_api_key_here"
    assert parsed["TREND_PROVIDER_STRICT"] == "false"

    combined_values = "\n".join(parsed.values())
    secret_like_patterns = [r"\bsk-proj-", r"\bAIza", r"\bxai-", r"\bsk-ant-"]
    assert all(re.search(pattern, combined_values) is None for pattern in secret_like_patterns)
