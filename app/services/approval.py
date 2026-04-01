from dataclasses import dataclass
from uuid import uuid4

from app.schemas.project import (
    ActorContext,
    ActorRole,
    ActorType,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    ProjectPolicy,
)


@dataclass
class AuthorizationDecision:
    allowed: bool
    reason: str
    effective_roles: set[ActorRole]
    effective_actor_ids: set[str] | None
    policy_source: str
    strict_mode: bool
    override_applied: bool


class ApprovalPolicy:
    """Centralized approval checks for high-risk operations."""

    APPROVAL_REQUIRED_ACTIONS = {
        ApprovalActionType.EXTERNAL_API_SEND,
        ApprovalActionType.DESTRUCTIVE_CHANGE,
        ApprovalActionType.BULK_MODIFY,
        ApprovalActionType.PRODUCTION_AFFECTING_CHANGE,
    }

    DEFAULT_ACTION_ROLE_RULES: dict[ApprovalActionType, set[ActorRole]] = {
        ApprovalActionType.EXTERNAL_API_SEND: {
            ActorRole.OWNER,
            ActorRole.APPROVER,
            ActorRole.ADMIN,
        },
        ApprovalActionType.DESTRUCTIVE_CHANGE: {
            ActorRole.APPROVER,
            ActorRole.ADMIN,
        },
        ApprovalActionType.BULK_MODIFY: {
            ActorRole.OPERATOR,
            ActorRole.APPROVER,
            ActorRole.ADMIN,
        },
        ApprovalActionType.PRODUCTION_AFFECTING_CHANGE: {
            ActorRole.ADMIN,
        },
    }

    def requires_human_approval(self, action_type: ApprovalActionType) -> bool:
        return action_type in self.APPROVAL_REQUIRED_ACTIONS

    @staticmethod
    def _normalize_actor_ids(actor_ids: list[str]) -> set[str]:
        normalized: set[str] = set()
        for actor_id in actor_ids:
            if not isinstance(actor_id, str):
                continue
            cleaned = actor_id.strip()
            if cleaned:
                normalized.add(cleaned)
        return normalized

    @staticmethod
    def _normalize_action_key(action_key: str) -> str:
        return action_key.strip().lower()

    def _find_action_mapping_value(
        self,
        action_mapping: dict[str, object],
        action_key: str,
    ) -> tuple[bool, object | None]:
        if action_key in action_mapping:
            return True, action_mapping[action_key]
        for candidate_key, candidate_value in action_mapping.items():
            if (
                isinstance(candidate_key, str)
                and self._normalize_action_key(candidate_key) == action_key
            ):
                return True, candidate_value
        return False, None

    def _find_project_action_rule(
        self,
        project_policy: ProjectPolicy,
        action_type: ApprovalActionType,
    ):
        found, rule = self._find_action_mapping_value(
            action_mapping=project_policy.action_rules,
            action_key=action_type.value,
        )
        return rule if found else None

    def _find_runtime_actor_ids(
        self,
        project_allowed_actor_ids_by_action: dict[str, list[str]] | None,
        action_type: ApprovalActionType,
    ) -> tuple[bool, list[str]]:
        if not project_allowed_actor_ids_by_action:
            return False, []
        found, raw_ids = self._find_action_mapping_value(
            action_mapping=project_allowed_actor_ids_by_action,
            action_key=action_type.value,
        )
        if not found:
            return False, []
        return True, raw_ids if isinstance(raw_ids, list) else []

    def _resolve_effective_policy(
        self,
        action_type: ApprovalActionType,
        project_policy: ProjectPolicy | None,
        project_allowed_actor_ids_by_action: dict[str, list[str]] | None,
    ) -> tuple[set[ActorRole], set[str] | None, str, bool, bool]:
        effective_roles = set(self.DEFAULT_ACTION_ROLE_RULES.get(action_type, set()))
        effective_actor_ids: set[str] | None = None
        policy_source = "default_rbac"
        strict_mode = False
        override_applied = False

        if project_policy:
            strict_mode = project_policy.strict_mode
            rule = self._find_project_action_rule(project_policy, action_type)
            if rule:
                policy_source = "project_policy"
                override_applied = True
                if rule.allowed_roles:
                    effective_roles = set(rule.allowed_roles)
                if rule.allowed_actor_ids:
                    effective_actor_ids = self._normalize_actor_ids(rule.allowed_actor_ids)
            elif strict_mode:
                return set(), set(), "project_policy_strict", strict_mode, True

        runtime_override_found, raw_ids = self._find_runtime_actor_ids(
            project_allowed_actor_ids_by_action,
            action_type,
        )
        if runtime_override_found:
            override_applied = True
            effective_actor_ids = self._normalize_actor_ids(raw_ids)
            policy_source = "project_runtime_override"

        return effective_roles, effective_actor_ids, policy_source, strict_mode, override_applied

    def authorize_action(
        self,
        action_type: ApprovalActionType,
        actor: ActorContext,
        project_policy: ProjectPolicy | None = None,
        project_allowed_actor_ids_by_action: dict[str, list[str]] | None = None,
    ) -> AuthorizationDecision:
        if actor.actor_role == ActorRole.VIEWER:
            return AuthorizationDecision(
                allowed=False,
                reason="viewer role cannot approve actions.",
                effective_roles=set(),
                effective_actor_ids=None,
                policy_source="default_rbac",
                strict_mode=False,
                override_applied=False,
            )

        (
            effective_roles,
            effective_actor_ids,
            policy_source,
            strict_mode,
            override_applied,
        ) = self._resolve_effective_policy(
            action_type=action_type,
            project_policy=project_policy,
            project_allowed_actor_ids_by_action=project_allowed_actor_ids_by_action,
        )

        actor_id = actor.actor_id.strip()
        actor_roles = {actor.actor_role}
        owner_actor_id = (
            (project_policy.project_owner_actor_id or "").strip() if project_policy else ""
        )
        if owner_actor_id and owner_actor_id == actor_id:
            actor_roles.add(ActorRole.OWNER)

        if strict_mode and not effective_roles:
            return AuthorizationDecision(
                allowed=False,
                reason=f"strict_mode requires explicit policy for `{action_type.value}`.",
                effective_roles=effective_roles,
                effective_actor_ids=effective_actor_ids,
                policy_source=policy_source,
                strict_mode=strict_mode,
                override_applied=override_applied,
            )

        if not actor_roles.intersection(effective_roles):
            return AuthorizationDecision(
                allowed=False,
                reason=(
                    f"role `{actor.actor_role.value}` is not allowed for `{action_type.value}` "
                    f"under `{policy_source}`."
                ),
                effective_roles=effective_roles,
                effective_actor_ids=effective_actor_ids,
                policy_source=policy_source,
                strict_mode=strict_mode,
                override_applied=override_applied,
            )

        if effective_actor_ids is not None and actor_id not in effective_actor_ids:
            return AuthorizationDecision(
                allowed=False,
                reason=f"actor `{actor_id}` is not in allowed actor IDs.",
                effective_roles=effective_roles,
                effective_actor_ids=effective_actor_ids,
                policy_source=policy_source,
                strict_mode=strict_mode,
                override_applied=override_applied,
            )

        return AuthorizationDecision(
            allowed=True,
            reason="authorized",
            effective_roles=effective_roles,
            effective_actor_ids=effective_actor_ids,
            policy_source=policy_source,
            strict_mode=strict_mode,
            override_applied=override_applied,
        )

    def create_request(
        self,
        action_type: ApprovalActionType,
        reason: str,
        requested_by: ActorContext | None = None,
    ) -> ApprovalRequest:
        requester = requested_by or ActorContext(
            actor_id="orchestrator",
            actor_role=ActorRole.ADMIN,
            actor_type=ActorType.SYSTEM,
        )
        return ApprovalRequest(
            id=f"approval-{uuid4()}",
            action_type=action_type,
            status=ApprovalStatus.PENDING,
            reason=reason,
            requested_by=requester.actor_id,
        )
