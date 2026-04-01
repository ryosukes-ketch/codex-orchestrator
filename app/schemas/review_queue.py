from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ReviewQueueStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class ReviewQueueItem(BaseModel):
    item_id: str = Field(min_length=1)
    current_task: str = Field(min_length=1)
    risk_level: Literal["low", "medium", "high"]
    department_routing: str = Field(min_length=1)
    hard_gate_status: bool
    hard_gate_triggers: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
    escalation_reasons: list[str] = Field(default_factory=list)
    recommendation: Literal["GO", "PAUSE", "REVIEW"]
    review_status: ReviewQueueStatus = ReviewQueueStatus.PENDING
    related_project_id: str | None = None
    related_brief_id: str | None = None
    related_work_order_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    note: str = ""
