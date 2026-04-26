import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import clear_auth_service_dependency_caches
from app.api.main import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_auth_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_auth_service_dependency_caches()
    monkeypatch.setenv("DEV_AUTH_ENABLED", "true")
    monkeypatch.delenv("DEV_AUTH_TOKEN_SEED", raising=False)
    yield
    clear_auth_service_dependency_caches()


def _load_sample_brief() -> dict:
    payload = json.loads((ROOT / "examples/briefs/sample_brief.json").read_text(encoding="utf-8"))
    return payload["brief"] if "brief" in payload else payload


def test_operator_contract_run_approve_and_audit() -> None:
    client = TestClient(create_app())
    run = client.post(
        "/orchestrator/run",
        json={"brief": _load_sample_brief(), "trend_provider": "gemini-flash-lite-latest"},
    )
    assert run.status_code == 200
    run_payload = run.json()
    project_id = run_payload["summary"]["project_id"]
    assert run_payload["summary"]["status"] == "waiting_approval"

    approved = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "operator approve",
            "trend_provider": "mock",
        },
        headers={"Authorization": "Bearer dev-approver-token"},
    )
    assert approved.status_code == 200
    assert approved.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    audit_payload = audit.json()
    assert audit_payload["status"] == "completed"
    assert any(event["event_type"] == "approval_approved" for event in audit_payload["events"])
    assert audit_payload["department_stage_summary"]
    assert audit_payload["department_stage_totals"]["total_stage_executions"] >= 1
    assert "total_llm_transport_fallbacks" in audit_payload["department_stage_totals"]
    assert any(
        item["department"] == "review" and item["stage_name"] == "FinalJudgment"
        for item in audit_payload["department_stage_summary"]
    )


def test_operator_contract_reject_revision_replanning_chain() -> None:
    client = TestClient(create_app())
    run = client.post(
        "/orchestrator/run",
        json={"brief": _load_sample_brief(), "trend_provider": "gemini-flash-lite-latest"},
    )
    assert run.status_code == 200
    project_id = run.json()["summary"]["project_id"]
    assert run.json()["summary"]["status"] == "waiting_approval"

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "Security policy",
            "note": "operator reject",
        },
        headers={"Authorization": "Bearer dev-approver-token"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    revised = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "Address reviewer concerns",
            "trend_provider": "mock",
        },
        headers={"Authorization": "Bearer dev-operator-token"},
    )
    assert revised.status_code == 200
    assert revised.json()["summary"]["status"] == "ready_for_planning"

    replanned = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "operator restart planning",
            "trend_provider": "mock",
            "approved_actions": [],
            "reset_downstream_tasks": True,
        },
        headers={"Authorization": "Bearer dev-operator-token"},
    )
    assert replanned.status_code == 200
    assert replanned.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["status"] == "completed"
    assert payload["department_stage_summary"]
    assert payload["department_stage_totals"]["total_stage_executions"] >= 1
    assert "total_llm_transport_fallbacks" in payload["department_stage_totals"]
    assert any(
        item["department"] == "build" and item["stage_name"] == "Tester"
        for item in payload["department_stage_summary"]
    )


def test_operator_contract_supports_commercial_token_auth_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_SERVICE_MODE", "commercial_token")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AUTH_TOKEN_SEED",
        "commercial-operator:ops-1:operator:human,commercial-approver:apr-1:approver:human",
    )

    client = TestClient(create_app())
    run = client.post(
        "/orchestrator/run",
        json={"brief": _load_sample_brief(), "trend_provider": "gemini-flash-lite-latest"},
    )
    assert run.status_code == 200
    project_id = run.json()["summary"]["project_id"]
    assert run.json()["summary"]["status"] == "waiting_approval"

    # Dev token should not authenticate when commercial_token mode is active.
    dev_attempt = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "dev token attempt",
            "trend_provider": "mock",
        },
        headers={"Authorization": "Bearer dev-approver-token"},
    )
    assert dev_attempt.status_code == 401

    approved = client.post(
        "/orchestrator/resume/approval",
        json={
            "project_id": project_id,
            "approved_actions": ["external_api_send"],
            "note": "commercial approve",
            "trend_provider": "mock",
        },
        headers={"Authorization": "Bearer commercial-approver"},
    )
    assert approved.status_code == 200
    assert approved.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["status"] == "completed"
    assert any(
        event["event_type"] == "actor_resolved" and event["actor"] == "apr-1"
        for event in payload["events"]
    )


def test_operator_contract_commercial_token_reject_revise_replan_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_SERVICE_MODE", "commercial_token")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AUTH_TOKEN_SEED",
        "commercial-operator:ops-1:operator:human,commercial-approver:apr-1:approver:human",
    )

    client = TestClient(create_app())
    run = client.post(
        "/orchestrator/run",
        json={"brief": _load_sample_brief(), "trend_provider": "gemini-flash-lite-latest"},
    )
    assert run.status_code == 200
    project_id = run.json()["summary"]["project_id"]
    assert run.json()["summary"]["status"] == "waiting_approval"

    # Dev token is no longer valid in commercial_token mode.
    dev_reject_attempt = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "dev token should fail in commercial mode",
        },
        headers={"Authorization": "Bearer dev-approver-token"},
    )
    assert dev_reject_attempt.status_code == 401

    rejected = client.post(
        "/orchestrator/approval/reject",
        json={
            "project_id": project_id,
            "rejected_actions": ["external_api_send"],
            "reason": "commercial rejection",
            "note": "commercial reject note",
        },
        headers={"Authorization": "Bearer commercial-approver"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["summary"]["status"] == "revision_requested"

    dev_revise_attempt = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "dev token should fail in commercial mode",
            "trend_provider": "mock",
        },
        headers={"Authorization": "Bearer dev-operator-token"},
    )
    assert dev_revise_attempt.status_code == 401

    revised = client.post(
        "/orchestrator/resume/revision",
        json={
            "project_id": project_id,
            "resume_mode": "replanning",
            "reason": "commercial revise",
            "trend_provider": "mock",
        },
        headers={"Authorization": "Bearer commercial-operator"},
    )
    assert revised.status_code == 200
    assert revised.json()["summary"]["status"] == "ready_for_planning"

    replanned = client.post(
        "/orchestrator/replanning/start",
        json={
            "project_id": project_id,
            "note": "commercial replan",
            "trend_provider": "mock",
            "approved_actions": [],
            "reset_downstream_tasks": True,
        },
        headers={"Authorization": "Bearer commercial-operator"},
    )
    assert replanned.status_code == 200
    assert replanned.json()["summary"]["status"] == "completed"

    audit = client.get(f"/projects/{project_id}/audit")
    assert audit.status_code == 200
    payload = audit.json()
    assert payload["status"] == "completed"
    assert any(
        event["event_type"] == "approval_rejected" and event["actor"] == "apr-1"
        for event in payload["events"]
    )
    assert any(
        event["event_type"] == "resume_triggered" and event["actor"] == "ops-1"
        for event in payload["events"]
    )
