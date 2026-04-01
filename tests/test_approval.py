from app.schemas.project import (
    ActorContext,
    ActorRole,
    ApprovalActionType,
    ProjectPolicy,
    ProjectPolicyActionRule,
)
from app.services.approval import ApprovalPolicy


def test_approval_policy_requires_all_defined_high_risk_actions() -> None:
    policy = ApprovalPolicy()

    assert policy.requires_human_approval(ApprovalActionType.EXTERNAL_API_SEND)
    assert policy.requires_human_approval(ApprovalActionType.DESTRUCTIVE_CHANGE)
    assert policy.requires_human_approval(ApprovalActionType.BULK_MODIFY)
    assert policy.requires_human_approval(ApprovalActionType.PRODUCTION_AFFECTING_CHANGE)


def test_approval_policy_creates_pending_request() -> None:
    policy = ApprovalPolicy()
    request = policy.create_request(
        action_type=ApprovalActionType.EXTERNAL_API_SEND,
        reason="Need external trend data",
    )

    assert request.action_type == ApprovalActionType.EXTERNAL_API_SEND
    assert request.status.value == "pending"
    assert request.reason == "Need external trend data"


def test_role_based_authorization_rules() -> None:
    policy = ApprovalPolicy()
    approver = ActorContext(actor_id="a1", actor_role=ActorRole.APPROVER)
    admin = ActorContext(actor_id="a2", actor_role=ActorRole.ADMIN)
    viewer = ActorContext(actor_id="a3", actor_role=ActorRole.VIEWER)

    decision = policy.authorize_action(ApprovalActionType.EXTERNAL_API_SEND, approver)
    assert decision.allowed

    decision = policy.authorize_action(ApprovalActionType.PRODUCTION_AFFECTING_CHANGE, admin)
    assert decision.allowed

    decision = policy.authorize_action(ApprovalActionType.EXTERNAL_API_SEND, viewer)
    assert not decision.allowed


def test_authorize_action_denies_when_strict_mode_missing_rule() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)
    project_policy = ProjectPolicy(strict_mode=True, action_rules={})

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_policy=project_policy,
    )

    assert decision.allowed is False
    assert decision.policy_source == "project_policy_strict"
    assert decision.strict_mode is True
    assert decision.override_applied is True
    assert "strict_mode requires explicit policy" in decision.reason


def test_authorize_action_applies_project_policy_actor_allowlist() -> None:
    policy = ApprovalPolicy()
    allowed_actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)
    denied_actor = ActorContext(actor_id="approver-2", actor_role=ActorRole.APPROVER)
    project_policy = ProjectPolicy(
        strict_mode=True,
        action_rules={
            ApprovalActionType.EXTERNAL_API_SEND.value: ProjectPolicyActionRule(
                allowed_roles=[ActorRole.APPROVER],
                allowed_actor_ids=["approver-1"],
            )
        },
    )

    allowed = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        allowed_actor,
        project_policy=project_policy,
    )
    denied = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        denied_actor,
        project_policy=project_policy,
    )

    assert allowed.allowed is True
    assert allowed.policy_source == "project_policy"
    assert allowed.override_applied is True
    assert denied.allowed is False
    assert "is not in allowed actor IDs" in denied.reason


def test_authorize_action_runtime_override_updates_policy_source() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_allowed_actor_ids_by_action={
            ApprovalActionType.EXTERNAL_API_SEND.value: ["approver-2"]
        },
    )

    assert decision.allowed is False
    assert decision.policy_source == "project_runtime_override"
    assert decision.override_applied is True
    assert "is not in allowed actor IDs" in decision.reason


def test_authorize_action_runtime_override_with_empty_allowlist_denies_all_actors() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_allowed_actor_ids_by_action={
            ApprovalActionType.EXTERNAL_API_SEND.value: []
        },
    )

    assert decision.allowed is False
    assert decision.policy_source == "project_runtime_override"
    assert decision.override_applied is True
    assert decision.effective_actor_ids == set()
    assert "is not in allowed actor IDs" in decision.reason


def test_authorize_action_runtime_override_takes_precedence_over_project_policy_source() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)
    project_policy = ProjectPolicy(
        strict_mode=True,
        action_rules={
            ApprovalActionType.EXTERNAL_API_SEND.value: ProjectPolicyActionRule(
                allowed_roles=[ActorRole.APPROVER],
                allowed_actor_ids=["approver-1"],
            )
        },
    )

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_policy=project_policy,
        project_allowed_actor_ids_by_action={
            ApprovalActionType.EXTERNAL_API_SEND.value: ["another-approver"]
        },
    )

    assert decision.allowed is False
    assert decision.policy_source == "project_runtime_override"
    assert decision.override_applied is True
    assert decision.effective_actor_ids == {"another-approver"}
    assert "is not in allowed actor IDs" in decision.reason


def test_authorize_action_project_policy_allowlist_normalizes_actor_ids() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)
    project_policy = ProjectPolicy(
        strict_mode=True,
        action_rules={
            ApprovalActionType.EXTERNAL_API_SEND.value: ProjectPolicyActionRule(
                allowed_roles=[ActorRole.APPROVER],
                allowed_actor_ids=[" approver-1 ", "", "approver-1", "   "],
            )
        },
    )

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_policy=project_policy,
    )

    assert decision.allowed is True
    assert decision.effective_actor_ids == {"approver-1"}


def test_authorize_action_project_policy_key_normalizes_whitespace_and_case() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)
    project_policy = ProjectPolicy(
        strict_mode=True,
        action_rules={
            "  EXTERNAL_API_SEND  ": ProjectPolicyActionRule(
                allowed_roles=[ActorRole.APPROVER],
            )
        },
    )

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_policy=project_policy,
    )

    assert decision.allowed is True
    assert decision.policy_source == "project_policy"


def test_authorize_action_runtime_override_normalizes_actor_ids() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_allowed_actor_ids_by_action={
            ApprovalActionType.EXTERNAL_API_SEND.value: [" approver-1 ", "", "  ", "approver-1"]
        },
    )

    assert decision.allowed is True
    assert decision.policy_source == "project_runtime_override"
    assert decision.effective_actor_ids == {"approver-1"}


def test_authorize_action_runtime_override_key_normalizes_whitespace_and_case() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="approver-1", actor_role=ActorRole.APPROVER)

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_allowed_actor_ids_by_action={
            "  EXTERNAL_API_SEND  ": ["approver-1"]
        },
    )

    assert decision.allowed is True
    assert decision.policy_source == "project_runtime_override"
    assert decision.override_applied is True


def test_authorize_action_normalizes_actor_id_for_allowlist_matching() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id=" approver-1 ", actor_role=ActorRole.APPROVER)

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_allowed_actor_ids_by_action={
            ApprovalActionType.EXTERNAL_API_SEND.value: ["approver-1"]
        },
    )

    assert decision.allowed is True
    assert decision.policy_source == "project_runtime_override"


def test_authorize_action_adds_owner_role_from_project_policy() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="owner-123", actor_role=ActorRole.OPERATOR)
    project_policy = ProjectPolicy(
        project_owner_actor_id="owner-123",
        action_rules={
            ApprovalActionType.EXTERNAL_API_SEND.value: ProjectPolicyActionRule(
                allowed_roles=[ActorRole.OWNER]
            )
        },
    )

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_policy=project_policy,
    )

    assert decision.allowed is True
    assert decision.policy_source == "project_policy"


def test_authorize_action_adds_owner_role_when_owner_id_has_surrounding_whitespace() -> None:
    policy = ApprovalPolicy()
    actor = ActorContext(actor_id="owner-123", actor_role=ActorRole.OPERATOR)
    project_policy = ProjectPolicy(
        project_owner_actor_id="  owner-123  ",
        action_rules={
            ApprovalActionType.EXTERNAL_API_SEND.value: ProjectPolicyActionRule(
                allowed_roles=[ActorRole.OWNER]
            )
        },
    )

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        actor,
        project_policy=project_policy,
    )

    assert decision.allowed is True
    assert decision.policy_source == "project_policy"


def test_authorize_action_viewer_is_denied_even_with_runtime_allowlist() -> None:
    policy = ApprovalPolicy()
    viewer = ActorContext(actor_id="viewer-1", actor_role=ActorRole.VIEWER)

    decision = policy.authorize_action(
        ApprovalActionType.EXTERNAL_API_SEND,
        viewer,
        project_allowed_actor_ids_by_action={
            ApprovalActionType.EXTERNAL_API_SEND.value: ["viewer-1"]
        },
    )

    assert decision.allowed is False
    assert decision.policy_source == "default_rbac"
    assert decision.override_applied is False
    assert decision.reason == "viewer role cannot approve actions."


def test_create_request_uses_explicit_requester() -> None:
    policy = ApprovalPolicy()
    requester = ActorContext(actor_id="service-1", actor_role=ActorRole.ADMIN)

    request = policy.create_request(
        action_type=ApprovalActionType.BULK_MODIFY,
        reason="Bulk operation needs approval.",
        requested_by=requester,
    )

    assert request.action_type == ApprovalActionType.BULK_MODIFY
    assert request.requested_by == "service-1"
    assert request.status.value == "pending"
