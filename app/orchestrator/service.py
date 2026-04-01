from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from app.agents.departments import BuildAgent, DesignAgent, ResearchAgent, ReviewAgent, TrendAgent
from app.orchestrator.graph import can_transition
from app.providers.factory import get_trend_provider
from app.schemas.brief import ProjectBrief
from app.schemas.project import (
    ActorContext,
    ActorRole,
    ActorType,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    Checkpoint,
    Department,
    HistoryEvent,
    HistoryEventType,
    OrchestrationResult,
    Project,
    ProjectAudit,
    ProjectPolicy,
    ProjectRecord,
    ProjectStatus,
    ProjectSummary,
    RevisionResumeMode,
    Task,
    TaskStatus,
)
from app.services.approval import ApprovalPolicy
from app.state.repository import ProjectRepository, create_repository_from_env


@dataclass(frozen=True)
class _ApprovalActionState:
    known_actions: set[ApprovalActionType]
    approved_actions: set[ApprovalActionType]
    rejected_actions: set[ApprovalActionType]
    pending_approvals: list[ApprovalRequest]
    pending_action_types: set[ApprovalActionType]


class PMOrchestrator:
    def __init__(
        self,
        repository: ProjectRepository | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self.repository = repository or create_repository_from_env()
        self.approval_policy = approval_policy or ApprovalPolicy()

    def _build_plan(self) -> list[Task]:
        return [
            Task(id="task-research", title="Research baseline", department=Department.RESEARCH),
            Task(
                id="task-design",
                title="Design architecture",
                department=Department.DESIGN,
                depends_on=["task-research"],
            ),
            Task(
                id="task-build",
                title="Build scaffold",
                department=Department.BUILD,
                depends_on=["task-design"],
            ),
            Task(
                id="task-trend",
                title="Trend analysis",
                department=Department.TREND,
                depends_on=["task-design"],
            ),
            Task(
                id="task-review",
                title="Review output",
                department=Department.REVIEW,
                depends_on=["task-build", "task-trend"],
            ),
        ]

    def _system_actor(self) -> ActorContext:
        return ActorContext(
            actor_id="system",
            actor_role=ActorRole.ADMIN,
            actor_type=ActorType.SYSTEM,
        )

    def _coerce_actor(
        self,
        actor: ActorContext | str | None,
        default_role: ActorRole = ActorRole.OPERATOR,
        default_type: ActorType = ActorType.HUMAN,
    ) -> ActorContext:
        if actor is None:
            return ActorContext(
                actor_id="unknown",
                actor_role=default_role,
                actor_type=default_type,
            )
        if isinstance(actor, ActorContext):
            return actor
        actor_id = actor.strip() or "unknown"
        return ActorContext(
            actor_id=actor_id,
            actor_role=default_role,
            actor_type=default_type,
        )

    def _record_event(
        self,
        record: ProjectRecord,
        event_type: HistoryEventType,
        actor: ActorContext | None = None,
        reason: str = "",
        metadata: dict | None = None,
    ) -> None:
        actor_context = actor or self._system_actor()
        event_metadata = deepcopy(metadata) if metadata else {}
        record.events.append(
            HistoryEvent(
                event_type=event_type,
                actor=actor_context.actor_id,
                actor_role=actor_context.actor_role,
                actor_type=actor_context.actor_type,
                reason=reason,
                metadata=event_metadata,
            )
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return value.strip()

    @staticmethod
    def _compose_decision_note(primary: str, secondary: str) -> str:
        return " ".join(part for part in (primary, secondary) if part)

    @staticmethod
    def _revision_resume_next_steps() -> list[str]:
        return ["Use revision resume API to continue with replanning/rebuilding/rereview."]

    @staticmethod
    def _replanning_start_next_steps() -> list[str]:
        return ["Call replanning start API to begin execution from ready_for_planning."]

    def _record_authorization_failure(
        self,
        record: ProjectRecord,
        actor: ActorContext,
        action_type: ApprovalActionType,
        message: str,
        policy_source: str | None = None,
        strict_mode: bool | None = None,
        override_applied: bool | None = None,
    ) -> None:
        self._record_event(
            record,
            event_type=HistoryEventType.AUTHORIZATION_FAILED,
            actor=actor,
            reason=message,
            metadata={
                "action_type": action_type.value,
                "policy_source": policy_source,
                "strict_mode": strict_mode,
                "override_applied": override_applied,
            },
        )

    def _record_authorization_granted(
        self,
        record: ProjectRecord,
        actor: ActorContext,
        action_type: ApprovalActionType,
        policy_source: str,
        strict_mode: bool,
        override_applied: bool,
    ) -> None:
        if override_applied:
            self._record_event(
                record,
                event_type=HistoryEventType.POLICY_OVERRIDE_APPLIED,
                actor=actor,
                reason="Project policy override was applied for authorization.",
                metadata={
                    "action_type": action_type.value,
                    "policy_source": policy_source,
                    "strict_mode": strict_mode,
                },
            )
        self._record_event(
            record,
            event_type=HistoryEventType.AUTHORIZATION_GRANTED,
            actor=actor,
            reason="Authorization granted.",
            metadata={
                "action_type": action_type.value,
                "policy_source": policy_source,
                "strict_mode": strict_mode,
            },
        )

    def _authorize_actions_or_raise(
        self,
        *,
        record: ProjectRecord,
        actor_context: ActorContext,
        action_types: set[ApprovalActionType],
        project_allowed_actor_ids_by_action: dict[str, list[str]] | None,
    ) -> None:
        for action_type in sorted(action_types, key=lambda item: item.value):
            decision = self.approval_policy.authorize_action(
                action_type=action_type,
                actor=actor_context,
                project_policy=record.project.policy,
                project_allowed_actor_ids_by_action=project_allowed_actor_ids_by_action,
            )
            if not decision.allowed:
                if decision.override_applied:
                    self._record_event(
                        record,
                        event_type=HistoryEventType.POLICY_OVERRIDE_APPLIED,
                        actor=actor_context,
                        reason="Project policy override was evaluated for authorization.",
                        metadata={
                            "action_type": action_type.value,
                            "policy_source": decision.policy_source,
                            "strict_mode": decision.strict_mode,
                        },
                    )
                self._record_authorization_failure(
                    record=record,
                    actor=actor_context,
                    action_type=action_type,
                    message=decision.reason,
                    policy_source=decision.policy_source,
                    strict_mode=decision.strict_mode,
                    override_applied=decision.override_applied,
                )
                self.repository.save(record)
                raise PermissionError(decision.reason)
            self._record_authorization_granted(
                record=record,
                actor=actor_context,
                action_type=action_type,
                policy_source=decision.policy_source,
                strict_mode=decision.strict_mode,
                override_applied=decision.override_applied,
            )

    def _transition(
        self,
        record: ProjectRecord,
        next_status: ProjectStatus,
        actor: ActorContext | None = None,
        reason: str = "",
    ) -> None:
        project = record.project
        current = project.status
        if current == next_status:
            return
        if not can_transition(current, next_status):
            raise ValueError(f"Invalid transition: {current} -> {next_status}")
        record.history.append(f"{current.value} -> {next_status.value}")
        project.status = next_status
        self._record_event(
            record,
            event_type=HistoryEventType.STATE_TRANSITION,
            actor=actor,
            reason=reason,
            metadata={"from": current.value, "to": next_status.value},
        )

    def _set_task_status(
        self,
        record: ProjectRecord,
        task: Task,
        next_status: TaskStatus,
        actor: ActorContext,
        reason: str = "",
    ) -> None:
        current = task.status
        if current == next_status:
            return
        task.status = next_status
        self._record_event(
            record,
            event_type=HistoryEventType.TASK_STATUS_CHANGED,
            actor=actor,
            reason=reason,
            metadata={"task_id": task.id, "from": current.value, "to": next_status.value},
        )

    def _reset_tasks_for_departments(
        self,
        *,
        record: ProjectRecord,
        departments: set[Department],
        next_status: TaskStatus,
        actor: ActorContext,
        reason: str,
        update_note: bool = False,
        note_reason: str = "",
    ) -> None:
        for task in record.tasks:
            if task.department in departments:
                self._set_task_status(
                    record,
                    task,
                    next_status,
                    actor=actor,
                    reason=reason,
                )
                if update_note:
                    task.note = note_reason or task.note

    def _reject_approval_request(
        self,
        *,
        record: ProjectRecord,
        approval: ApprovalRequest,
        actor_context: ActorContext,
        reason: str,
        note: str,
        auto_closed: bool = False,
    ) -> None:
        approval.status = ApprovalStatus.REJECTED
        approval.requested_by = actor_context.actor_id
        approval.decision_note = self._compose_decision_note(reason, note)
        event_metadata = {"action_type": approval.action_type.value, "note": note}
        if auto_closed:
            event_metadata["auto_closed"] = True
        self._record_event(
            record,
            event_type=HistoryEventType.APPROVAL_REJECTED,
            actor=actor_context,
            reason=reason,
            metadata=event_metadata,
        )
        self._update_approval_checkpoint(
            record,
            approved=False,
            approver=actor_context.actor_id,
            note=approval.decision_note,
        )

    def _upsert_checkpoint(self, record, checkpoint) -> None:
        for index, existing in enumerate(record.checkpoints):
            if existing.id == checkpoint.id:
                record.checkpoints[index] = checkpoint
                return
        record.checkpoints.append(checkpoint)
    def _update_approval_checkpoint(
        self,
        record,
        *,
        approved: bool,
        approver: str,
        note: str | None = None,
    ) -> None:
        checkpoint_id = f"checkpoint-approval-{record.project.id}"
        for checkpoint in record.checkpoints:
            if checkpoint.id == checkpoint_id:
                checkpoint.approved = approved
                checkpoint.approver = approver
                if note is not None:
                    checkpoint.note = note
                return

    def _parse_approved_actions(
        self, approved_actions: list[str] | set[ApprovalActionType] | None
    ) -> set[ApprovalActionType]:
        if not approved_actions:
            return set()
        parsed: set[ApprovalActionType] = set()
        for action in approved_actions:
            if isinstance(action, ApprovalActionType):
                parsed.add(action)
                continue
            if not isinstance(action, str):
                raise ValueError(f"Unsupported approval action value: {action!r}")
            normalized = action.strip().lower()
            if not normalized:
                raise ValueError(f"Unsupported approval action value: {action!r}")
            try:
                parsed.add(ApprovalActionType(normalized))
            except ValueError as exc:
                raise ValueError(f"Unsupported approval action value: {action!r}") from exc
        return parsed

    def _build_action_set_loader(
        self,
        actions: list[str] | set[ApprovalActionType] | None,
    ) -> Callable[[], set[ApprovalActionType]]:
        parsed_action_set_cache: set[ApprovalActionType] | None = None

        def _get_action_set() -> set[ApprovalActionType]:
            nonlocal parsed_action_set_cache
            if parsed_action_set_cache is None:
                parsed_action_set_cache = self._parse_approved_actions(actions)
            return parsed_action_set_cache

        return _get_action_set

    def _build_approval_action_state_loader(
        self,
        record: ProjectRecord,
    ) -> Callable[[], _ApprovalActionState]:
        action_state_cache: _ApprovalActionState | None = None

        def _get_action_state() -> _ApprovalActionState:
            nonlocal action_state_cache
            if action_state_cache is None:
                action_state_cache = self._approval_action_state(record)
            return action_state_cache

        return _get_action_state

    @staticmethod
    def _format_action_values(actions: set[ApprovalActionType]) -> str:
        return ", ".join(sorted(action.value for action in actions))

    @staticmethod
    def _approval_action_state(record: ProjectRecord) -> _ApprovalActionState:
        known_actions: set[ApprovalActionType] = set()
        approved_actions: set[ApprovalActionType] = set()
        rejected_actions: set[ApprovalActionType] = set()
        pending_approvals: list[ApprovalRequest] = []
        pending_action_types: set[ApprovalActionType] = set()

        for approval in record.approvals:
            action_type = approval.action_type
            known_actions.add(action_type)
            if approval.status == ApprovalStatus.APPROVED:
                approved_actions.add(action_type)
            elif approval.status == ApprovalStatus.REJECTED:
                rejected_actions.add(action_type)
            elif approval.status == ApprovalStatus.PENDING:
                pending_approvals.append(approval)
                pending_action_types.add(action_type)

        return _ApprovalActionState(
            known_actions=known_actions,
            approved_actions=approved_actions,
            rejected_actions=rejected_actions,
            pending_approvals=pending_approvals,
            pending_action_types=pending_action_types,
        )

    @classmethod
    def _formatted_missing_actions(
        cls,
        missing_actions: set[ApprovalActionType],
    ) -> tuple[str, str]:
        missing_action_values = sorted(action.value for action in missing_actions)
        missing = ", ".join(missing_action_values)
        approved_actions_payload = ", ".join(f"\"{action}\"" for action in missing_action_values)
        return missing, approved_actions_payload

    @classmethod
    def _raise_if_actions_outside_allowed_set(
        cls,
        *,
        requested_actions: set[ApprovalActionType],
        allowed_actions: set[ApprovalActionType],
        error_prefix: str,
    ) -> None:
        disallowed_actions = requested_actions - allowed_actions
        if disallowed_actions:
            raise ValueError(f"{error_prefix}: {cls._format_action_values(disallowed_actions)}")

    @classmethod
    def _raise_if_actions_previously_rejected(
        cls,
        *,
        requested_actions: set[ApprovalActionType],
        rejected_actions: set[ApprovalActionType],
        error_prefix: str,
    ) -> None:
        already_rejected = requested_actions.intersection(rejected_actions)
        if already_rejected:
            raise ValueError(f"{error_prefix}: {cls._format_action_values(already_rejected)}")

    @classmethod
    def _validate_approval_action_request(
        cls,
        *,
        requested_actions: set[ApprovalActionType],
        known_actions: set[ApprovalActionType],
        rejected_actions: set[ApprovalActionType],
    ) -> None:
        cls._raise_if_actions_outside_allowed_set(
            requested_actions=requested_actions,
            allowed_actions=known_actions,
            error_prefix="Unknown approval action(s)",
        )
        cls._raise_if_actions_previously_rejected(
            requested_actions=requested_actions,
            rejected_actions=rejected_actions,
            error_prefix="Action(s) already rejected",
        )

    def _summary(self, record: ProjectRecord, next_steps: list[str]) -> OrchestrationResult:
        summary = ProjectSummary(
            project_id=record.project.id,
            status=record.project.status,
            completed_tasks=len([task for task in record.tasks if task.status == TaskStatus.DONE]),
            artifact_count=len(record.artifacts),
            next_steps=next_steps,
        )
        return OrchestrationResult(record=record, summary=summary)

    def _upsert_artifact(self, record, artifact) -> None:
        for index, existing in enumerate(record.artifacts):
            if existing.id == artifact.id:
                record.artifacts[index] = artifact
                return
        record.artifacts.append(artifact)

    def _execute_pending_tasks(
        self,
        record: ProjectRecord,
        trend_provider_name: str,
        approved_action_set: set[ApprovalActionType],
        simulate_review_failure: bool = False,
        actor: ActorContext | None = None,
    ) -> OrchestrationResult:
        actor_context = actor or self._system_actor()
        brief = record.project.brief
        research_agent = ResearchAgent()
        design_agent = DesignAgent()
        build_agent = BuildAgent()
        trend_agent = TrendAgent(provider=get_trend_provider(trend_provider_name))
        review_agent = ReviewAgent()

        current_cycle_review_failed = False
        review_ran = False

        for task in record.tasks:
            if task.status == TaskStatus.DONE:
                continue

            self._set_task_status(record, task, TaskStatus.IN_PROGRESS, actor=actor_context)

            if task.department == Department.RESEARCH:
                self._upsert_artifact(record, research_agent.run(task, brief))
            elif task.department == Department.DESIGN:
                self._upsert_artifact(record, design_agent.run(task, brief))
            elif task.department == Department.BUILD:
                self._upsert_artifact(record, build_agent.run(task, brief))
            elif task.department == Department.TREND:
                approval_action = ApprovalActionType.EXTERNAL_API_SEND
                if trend_agent.provider.name.strip().lower() != "mock":
                    if self.approval_policy.requires_human_approval(
                        approval_action
                    ) and approval_action not in approved_action_set:
                        self._set_task_status(
                            record,
                            task,
                            TaskStatus.WAITING_APPROVAL,
                            actor=actor_context,
                            reason="Required action approval is missing.",
                        )
                        pending_same_action = any(
                            approval.action_type == approval_action
                            and approval.status == ApprovalStatus.PENDING
                            for approval in record.approvals
                        )
                        if not pending_same_action:
                            approval_request = self.approval_policy.create_request(
                                action_type=approval_action,
                                reason=(
                                    "Trend analysis with external provider requires human approval."
                                ),
                                requested_by=self._system_actor(),
                            )
                            record.approvals.append(approval_request)
                            self._record_event(
                                record,
                                event_type=HistoryEventType.APPROVAL_REQUESTED,
                                actor=self._system_actor(),
                                reason=approval_request.reason,
                                metadata={"action_type": approval_action.value},
                            )

                        self._upsert_checkpoint(
                            record,
                            Checkpoint(
                                id=f"checkpoint-approval-{record.project.id}",
                                name="External provider approval",
                                approved=False,
                                approver="human",
                                note="Approve `external_api_send` to continue trend analysis.",
                            )
                        )
                        self._transition(
                            record,
                            ProjectStatus.WAITING_APPROVAL,
                            actor=actor_context,
                            reason="Execution paused for approval.",
                        )
                        self.repository.save(record)
                        return self._summary(
                            record,
                            next_steps=[
                                "Approve action `external_api_send`.",
                                (
                                    "Call approval resume API with "
                                    "`approved_actions=[\"external_api_send\"]`."
                                ),
                            ],
                        )
                self._upsert_artifact(record, trend_agent.run(task, brief))
            elif task.department == Department.REVIEW:
                review = review_agent.run(task, record.artifacts)
                review_ran = True
                if simulate_review_failure:
                    review.verdict = "changes_requested"
                    if "Simulated review failure for rollback flow test." not in review.findings:
                        review.findings.append("Simulated review failure for rollback flow test.")
                current_cycle_review_failed = review.verdict == "changes_requested"
                record.reviews.append(review)

            self._set_task_status(record, task, TaskStatus.DONE, actor=actor_context)

        if review_ran and current_cycle_review_failed:
            self._transition(
                record,
                ProjectStatus.REVIEW_FAILED,
                actor=actor_context,
                reason="Review returned blocking findings.",
            )
            self._transition(
                record,
                ProjectStatus.REVISION_REQUESTED,
                actor=actor_context,
                reason="Revision requested after review failure.",
            )
            self._record_event(
                record,
                event_type=HistoryEventType.REVISION_REQUESTED,
                actor=actor_context,
                reason="Review requested revisions.",
            )
            self.repository.save(record)
            return self._summary(
                record,
                next_steps=[
                    "Use revision resume API with `resume_mode`.",
                    "Provide revision reason and actor for audit logging.",
                ],
            )

        self._upsert_checkpoint(
            record,
            Checkpoint(
                id=f"checkpoint-{record.project.id}",
                name="Delivery checkpoint",
                approved=True,
                approver="system",
                note="Auto-approved for deterministic scaffold run.",
            )
        )
        self._transition(
            record,
            ProjectStatus.COMPLETED,
            actor=actor_context,
            reason="Execution finished without blocking review findings.",
        )
        self.repository.save(record)
        return self._summary(
            record,
            next_steps=[
                "Connect real provider APIs with approval gate.",
                "Move DB bootstrap SQL to managed migrations.",
            ],
        )

    def run(
        self,
        brief: ProjectBrief,
        project_policy: ProjectPolicy | None = None,
        trend_provider_name: str = "mock",
        approved_actions: list[str] | set[ApprovalActionType] | None = None,
        simulate_review_failure: bool = False,
    ) -> OrchestrationResult:
        project = Project(
            id=str(uuid4()),
            brief=brief,
            policy=project_policy or ProjectPolicy(),
            status=ProjectStatus.DRAFT,
        )
        record = ProjectRecord(project=project, tasks=self._build_plan())
        approved_action_set = self._parse_approved_actions(approved_actions)

        self._transition(
            record,
            ProjectStatus.INTAKE_PENDING,
            actor=self._system_actor(),
            reason="Brief intake started.",
        )
        self._transition(
            record,
            ProjectStatus.READY_FOR_PLANNING,
            actor=self._system_actor(),
            reason="Brief accepted for planning.",
        )
        self._transition(
            record,
            ProjectStatus.IN_PROGRESS,
            actor=self._system_actor(),
            reason="Execution started.",
        )
        return self._execute_pending_tasks(
            record=record,
            trend_provider_name=trend_provider_name,
            approved_action_set=approved_action_set,
            simulate_review_failure=simulate_review_failure,
            actor=self._system_actor(),
        )

    def _get_record_or_raise(self, project_id: str) -> ProjectRecord:
        record = self.repository.get(project_id)
        if not record:
            raise LookupError(f"Project not found: {project_id}")
        return record

    def record_authentication_success(self, project_id: str, actor: ActorContext) -> None:
        try:
            record = self._get_record_or_raise(project_id)
        except LookupError:
            return
        self._record_event(
            record,
            event_type=HistoryEventType.AUTHENTICATION_SUCCEEDED,
            actor=actor,
            reason="Authentication succeeded.",
        )
        self._record_event(
            record,
            event_type=HistoryEventType.ACTOR_RESOLVED,
            actor=actor,
            reason="Actor resolved from authentication context.",
        )
        self.repository.save(record)

    def record_authentication_failure(self, project_id: str, reason: str) -> None:
        try:
            record = self._get_record_or_raise(project_id)
        except LookupError:
            return
        self._record_event(
            record,
            event_type=HistoryEventType.AUTHENTICATION_FAILED,
            actor=ActorContext(
                actor_id="anonymous",
                actor_role=ActorRole.VIEWER,
                actor_type=ActorType.HUMAN,
            ),
            reason=reason,
        )
        self.repository.save(record)

    @staticmethod
    def _invalid_state_error(
        *,
        expected_status: ProjectStatus,
        current_status: ProjectStatus,
    ) -> ValueError:
        return ValueError(
            (
                f"Project is not in {expected_status.value} state "
                f"(current: {current_status.value})."
            )
        )

    def _resolve_result_or_raise_invalid_state(
        self,
        *,
        record: ProjectRecord,
        expected_status: ProjectStatus,
        idempotent_handlers: tuple[Callable[[], OrchestrationResult | None], ...] = (),
    ) -> OrchestrationResult | None:
        if record.project.status == expected_status:
            return None
        for idempotent_handler in idempotent_handlers:
            idempotent_result = idempotent_handler()
            if idempotent_result is not None:
                return idempotent_result
        raise self._invalid_state_error(
            expected_status=expected_status,
            current_status=record.project.status,
        )

    def _idempotent_resume_from_approval_if_completed(
        self,
        *,
        record: ProjectRecord,
        approved_action_set: set[ApprovalActionType],
    ) -> OrchestrationResult | None:
        if record.project.status != ProjectStatus.COMPLETED:
            return None

        action_state = self._approval_action_state(record)
        if not action_state.known_actions:
            return None
        self._validate_approval_action_request(
            requested_actions=approved_action_set,
            known_actions=action_state.known_actions,
            rejected_actions=action_state.rejected_actions,
        )
        if not action_state.pending_approvals and approved_action_set.issubset(
            action_state.approved_actions
        ):
            return self._summary(
                record,
                next_steps=[
                    "Project already completed; approval resume request treated as idempotent.",
                ],
            )
        return None

    def _idempotent_reject_if_revision_requested(
        self,
        *,
        record: ProjectRecord,
        rejected_action_set: set[ApprovalActionType],
    ) -> OrchestrationResult | None:
        if record.project.status != ProjectStatus.REVISION_REQUESTED:
            return None

        action_state = self._approval_action_state(record)
        self._raise_if_actions_outside_allowed_set(
            requested_actions=rejected_action_set,
            allowed_actions=action_state.rejected_actions,
            error_prefix="Cannot reject non-pending action(s)",
        )

        if rejected_action_set and rejected_action_set.issubset(action_state.rejected_actions):
            return self._summary(
                record,
                next_steps=self._revision_resume_next_steps(),
            )
        return None

    def _idempotent_resume_from_revision_if_ready_for_planning(
        self,
        *,
        record: ProjectRecord,
        resume_mode: RevisionResumeMode,
    ) -> OrchestrationResult | None:
        if (
            record.project.status == ProjectStatus.READY_FOR_PLANNING
            and resume_mode == RevisionResumeMode.REPLANNING
        ):
            return self._summary(
                record,
                next_steps=self._replanning_start_next_steps(),
            )
        return None

    def _idempotent_resume_from_revision_if_completed(
        self,
        *,
        record: ProjectRecord,
        resume_mode: RevisionResumeMode,
    ) -> OrchestrationResult | None:
        return self._idempotent_if_completed_with_event(
            record=record,
            event_type=HistoryEventType.RESUME_TRIGGERED,
            mode=resume_mode.value,
            next_step="Project already completed; revision resume request treated as idempotent.",
        )

    def _idempotent_if_completed_with_event(
        self,
        *,
        record: ProjectRecord,
        event_type: HistoryEventType,
        next_step: str,
        mode: str | None = None,
    ) -> OrchestrationResult | None:
        if record.project.status != ProjectStatus.COMPLETED:
            return None
        event_found = self._has_event(
            record=record,
            event_type=event_type,
            mode=mode,
        )
        if not event_found:
            return None
        return self._summary(
            record,
            next_steps=[next_step],
        )

    def _idempotent_start_replanning_if_completed(
        self,
        *,
        record: ProjectRecord,
    ) -> OrchestrationResult | None:
        return self._idempotent_if_completed_with_event(
            record=record,
            event_type=HistoryEventType.REPLANNING_STARTED,
            next_step="Project already completed; replanning start request treated as idempotent.",
        )

    @staticmethod
    def _has_event(
        *,
        record: ProjectRecord,
        event_type: HistoryEventType,
        mode: str | None = None,
    ) -> bool:
        for event in record.events:
            if event.event_type != event_type:
                continue
            if mode is not None and event.metadata.get("mode") != mode:
                continue
            return True
        return False

    def _record_resume_triggered(
        self,
        *,
        record: ProjectRecord,
        actor_context: ActorContext,
        mode: str,
        reason: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        event_metadata: dict[str, str] = {"mode": mode}
        if metadata:
            event_metadata.update(metadata)
        self._record_event(
            record,
            event_type=HistoryEventType.RESUME_TRIGGERED,
            actor=actor_context,
            reason=reason,
            metadata=event_metadata,
        )

    def resume_from_approval(
        self,
        project_id: str,
        approved_actions: list[str] | set[ApprovalActionType],
        actor: ActorContext | str | None = None,
        note: str = "",
        trend_provider_name: str = "mock",
        project_allowed_actor_ids_by_action: dict[str, list[str]] | None = None,
    ) -> OrchestrationResult:
        actor_context = self._coerce_actor(actor, default_role=ActorRole.APPROVER)
        note_clean = self._normalize_text(note)
        record = self._get_record_or_raise(project_id)
        get_approved_action_set = self._build_action_set_loader(approved_actions)
        get_action_state = self._build_approval_action_state_loader(record)

        def _approval_completed_idempotent_handler() -> OrchestrationResult | None:
            if record.project.status == ProjectStatus.COMPLETED:
                approved_action_set = get_approved_action_set()
                if not approved_action_set:
                    raise ValueError("approved_actions is required.")
                return self._idempotent_resume_from_approval_if_completed(
                    record=record,
                    approved_action_set=approved_action_set,
                )
            return None

        idempotent_result = self._resolve_result_or_raise_invalid_state(
            record=record,
            expected_status=ProjectStatus.WAITING_APPROVAL,
            idempotent_handlers=(_approval_completed_idempotent_handler,),
        )
        if idempotent_result:
            return idempotent_result
        approved_action_set = get_approved_action_set()
        if not approved_action_set:
            raise ValueError("approved_actions is required.")
        action_state = get_action_state()
        pending_approvals = action_state.pending_approvals
        if not pending_approvals:
            raise ValueError("No pending approvals found.")
        self._validate_approval_action_request(
            requested_actions=approved_action_set,
            known_actions=action_state.known_actions,
            rejected_actions=action_state.rejected_actions,
        )

        required_actions = action_state.pending_action_types
        actions_to_approve = approved_action_set - action_state.approved_actions
        missing_actions = required_actions - approved_action_set

        if actions_to_approve:
            self._authorize_actions_or_raise(
                record=record,
                actor_context=actor_context,
                action_types=actions_to_approve,
                project_allowed_actor_ids_by_action=project_allowed_actor_ids_by_action,
            )

        for approval in pending_approvals:
            if approval.action_type in actions_to_approve:
                approval.status = ApprovalStatus.APPROVED
                approval.requested_by = actor_context.actor_id
                approval.decision_note = note_clean
                self._update_approval_checkpoint(
                    record,
                    approved=True,
                    approver=actor_context.actor_id,
                    note=note_clean or "Approved `external_api_send` to continue trend analysis.",
                )
                self._record_event(
                    record,
                    event_type=HistoryEventType.APPROVAL_APPROVED,
                    actor=actor_context,
                    reason=note_clean or "Approval granted.",
                    metadata={"action_type": approval.action_type.value},
                )

        if missing_actions:
            missing, approved_actions_payload = self._formatted_missing_actions(missing_actions)
            if actions_to_approve:
                self._record_resume_triggered(
                    record=record,
                    actor_context=actor_context,
                    mode="approval_resume_partial",
                    reason=note_clean or "Partial approval recorded.",
                    metadata={"missing_actions": missing},
                )
                self.repository.save(record)
            return self._summary(
                record,
                next_steps=[
                    f"Approve remaining action(s): {missing}.",
                    (
                        "Call approval resume API with "
                        f"`approved_actions=[{approved_actions_payload}]`."
                    ),
                ],
            )

        for task in record.tasks:
            if task.status == TaskStatus.WAITING_APPROVAL:
                self._set_task_status(record, task, TaskStatus.PENDING, actor=actor_context)

        self._record_resume_triggered(
            record=record,
            actor_context=actor_context,
            mode="approval_resume",
            reason=note_clean or "Approval resume requested.",
        )
        self._transition(
            record,
            ProjectStatus.IN_PROGRESS,
            actor=actor_context,
            reason="Approval requirements satisfied.",
        )
        effective_approved_action_set = action_state.approved_actions.union(actions_to_approve)
        return self._execute_pending_tasks(
            record=record,
            trend_provider_name=trend_provider_name,
            approved_action_set=effective_approved_action_set,
            actor=actor_context,
        )

    def reject_approval(
        self,
        project_id: str,
        rejected_actions: list[str] | set[ApprovalActionType] | None,
        actor: ActorContext | str | None,
        reason: str,
        note: str = "",
        project_allowed_actor_ids_by_action: dict[str, list[str]] | None = None,
    ) -> OrchestrationResult:
        actor_context = self._coerce_actor(actor, default_role=ActorRole.APPROVER)
        reason_clean = self._normalize_text(reason)
        note_clean = self._normalize_text(note)
        record = self._get_record_or_raise(project_id)
        if not reason_clean:
            raise ValueError("reason is required for approval rejection.")
        get_rejected_action_set = self._build_action_set_loader(rejected_actions)
        get_action_state = self._build_approval_action_state_loader(record)

        def _revision_requested_idempotent_handler() -> OrchestrationResult | None:
            if record.project.status == ProjectStatus.REVISION_REQUESTED:
                rejected_action_set = get_rejected_action_set()
                if not rejected_action_set:
                    rejected_action_set = get_action_state().rejected_actions
                return self._idempotent_reject_if_revision_requested(
                    record=record,
                    rejected_action_set=rejected_action_set,
                )
            return None

        idempotent_result = self._resolve_result_or_raise_invalid_state(
            record=record,
            expected_status=ProjectStatus.WAITING_APPROVAL,
            idempotent_handlers=(_revision_requested_idempotent_handler,),
        )
        if idempotent_result:
            return idempotent_result

        action_state = get_action_state()
        pending_approvals = action_state.pending_approvals
        if not pending_approvals:
            raise ValueError("No pending approvals found.")

        pending_action_set = action_state.pending_action_types
        rejected_action_set = get_rejected_action_set() or pending_action_set
        self._raise_if_actions_outside_allowed_set(
            requested_actions=rejected_action_set,
            allowed_actions=pending_action_set,
            error_prefix="Cannot reject non-pending action(s)",
        )

        self._authorize_actions_or_raise(
            record=record,
            actor_context=actor_context,
            action_types=pending_action_set,
            project_allowed_actor_ids_by_action=project_allowed_actor_ids_by_action,
        )

        for approval in pending_approvals:
            self._reject_approval_request(
                record=record,
                approval=approval,
                actor_context=actor_context,
                reason=reason_clean,
                note=note_clean,
                auto_closed=approval.action_type not in rejected_action_set,
            )

        for task in record.tasks:
            if task.status == TaskStatus.WAITING_APPROVAL:
                self._set_task_status(
                    record,
                    task,
                    TaskStatus.REVISION_REQUESTED,
                    actor=actor_context,
                    reason="Approval rejected.",
                )
                task.note = reason_clean

        self._transition(
            record,
            ProjectStatus.REVISION_REQUESTED,
            actor=actor_context,
            reason="Approval rejected; moved to revision lane.",
        )
        self.repository.save(record)
        return self._summary(
            record,
            next_steps=self._revision_resume_next_steps(),
        )

    def _resume_revision_with_transition(
        self,
        *,
        record: ProjectRecord,
        actor_context: ActorContext,
        reason_clean: str,
        departments: set[Department],
        task_reset_reason: str,
        next_status: ProjectStatus,
        transition_reason: str,
    ) -> None:
        self._reset_tasks_for_departments(
            record=record,
            departments=departments,
            next_status=TaskStatus.PENDING,
            actor=actor_context,
            reason=task_reset_reason,
            update_note=True,
            note_reason=reason_clean,
        )
        self._transition(
            record,
            next_status,
            actor=actor_context,
            reason=reason_clean or transition_reason,
        )

    @staticmethod
    def _revision_resume_config(
        resume_mode: RevisionResumeMode,
    ) -> tuple[set[Department], str, ProjectStatus, str]:
        if resume_mode == RevisionResumeMode.REPLANNING:
            return (
                {
                    Department.DESIGN,
                    Department.BUILD,
                    Department.TREND,
                    Department.REVIEW,
                },
                "Replanning requested.",
                ProjectStatus.READY_FOR_PLANNING,
                "Moved back to planning lane.",
            )
        if resume_mode == RevisionResumeMode.REBUILDING:
            return (
                {Department.BUILD, Department.TREND, Department.REVIEW},
                "Rebuilding requested.",
                ProjectStatus.IN_PROGRESS,
                "Rebuild flow resumed.",
            )
        # RevisionResumeMode.REREVIEW
        return (
            {Department.REVIEW},
            "Re-review requested.",
            ProjectStatus.IN_PROGRESS,
            "Re-review flow resumed.",
        )

    def _resume_revision_for_mode(
        self,
        *,
        record: ProjectRecord,
        actor_context: ActorContext,
        reason_clean: str,
        resume_mode: RevisionResumeMode,
        trend_provider_name: str,
        approved_actions: list[str] | set[ApprovalActionType] | None,
    ) -> OrchestrationResult:
        (
            departments,
            task_reset_reason,
            next_status,
            transition_reason,
        ) = self._revision_resume_config(resume_mode)
        self._resume_revision_with_transition(
            record=record,
            actor_context=actor_context,
            reason_clean=reason_clean,
            departments=departments,
            task_reset_reason=task_reset_reason,
            next_status=next_status,
            transition_reason=transition_reason,
        )
        if next_status == ProjectStatus.READY_FOR_PLANNING:
            self.repository.save(record)
            return self._summary(
                record,
                next_steps=self._replanning_start_next_steps(),
            )
        return self._execute_pending_tasks(
            record=record,
            trend_provider_name=trend_provider_name,
            approved_action_set=self._parse_approved_actions(approved_actions),
            actor=actor_context,
        )

    def resume_from_revision(
        self,
        project_id: str,
        resume_mode: RevisionResumeMode,
        actor: ActorContext | str | None = None,
        reason: str = "",
        trend_provider_name: str = "mock",
        approved_actions: list[str] | set[ApprovalActionType] | None = None,
    ) -> OrchestrationResult:
        actor_context = self._coerce_actor(actor, default_role=ActorRole.OPERATOR)
        reason_clean = self._normalize_text(reason)
        record = self._get_record_or_raise(project_id)
        idempotent_result = self._resolve_result_or_raise_invalid_state(
            record=record,
            expected_status=ProjectStatus.REVISION_REQUESTED,
            idempotent_handlers=(
                lambda: self._idempotent_resume_from_revision_if_ready_for_planning(
                    record=record,
                    resume_mode=resume_mode,
                ),
                lambda: self._idempotent_resume_from_revision_if_completed(
                    record=record,
                    resume_mode=resume_mode,
                ),
            ),
        )
        if idempotent_result:
            return idempotent_result

        self._record_resume_triggered(
            record=record,
            actor_context=actor_context,
            mode=resume_mode.value,
            reason=reason_clean or "Revision resume requested.",
        )

        return self._resume_revision_for_mode(
            record=record,
            actor_context=actor_context,
            reason_clean=reason_clean,
            resume_mode=resume_mode,
            trend_provider_name=trend_provider_name,
            approved_actions=approved_actions,
        )

    def start_replanning(
        self,
        project_id: str,
        actor: ActorContext | str | None,
        note: str = "",
        trend_provider_name: str = "mock",
        approved_actions: list[str] | set[ApprovalActionType] | None = None,
        reset_downstream_tasks: bool = True,
    ) -> OrchestrationResult:
        actor_context = self._coerce_actor(actor, default_role=ActorRole.OPERATOR)
        note_clean = self._normalize_text(note)
        record = self._get_record_or_raise(project_id)

        def _completed_replanning_idempotent_handler() -> OrchestrationResult | None:
            return self._idempotent_start_replanning_if_completed(record=record)

        idempotent_result = self._resolve_result_or_raise_invalid_state(
            record=record,
            expected_status=ProjectStatus.READY_FOR_PLANNING,
            idempotent_handlers=(_completed_replanning_idempotent_handler,),
        )
        if idempotent_result:
            return idempotent_result

        if reset_downstream_tasks:
            self._reset_tasks_for_departments(
                record=record,
                departments={
                    Department.DESIGN,
                    Department.BUILD,
                    Department.TREND,
                    Department.REVIEW,
                },
                next_status=TaskStatus.PENDING,
                actor=actor_context,
                reason="Replanning start reset.",
            )

        self._record_event(
            record,
            event_type=HistoryEventType.REPLANNING_STARTED,
            actor=actor_context,
            reason=note_clean or "Replanning execution started.",
            metadata={"reset_downstream_tasks": reset_downstream_tasks},
        )
        self._transition(
            record,
            ProjectStatus.IN_PROGRESS,
            actor=actor_context,
            reason="Replanning execution moved to in_progress.",
        )
        return self._execute_pending_tasks(
            record=record,
            trend_provider_name=trend_provider_name,
            approved_action_set=self._parse_approved_actions(approved_actions),
            actor=actor_context,
        )

    def get_project_audit(self, project_id: str) -> ProjectAudit:
        record = self._get_record_or_raise(project_id)
        return ProjectAudit(
            project_id=record.project.id,
            status=record.project.status,
            history=record.history,
            events=record.events,
            approvals=record.approvals,
            reviews=record.reviews,
            checkpoints=record.checkpoints,
        )

