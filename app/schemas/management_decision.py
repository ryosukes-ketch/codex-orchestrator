from typing import Literal

from pydantic import BaseModel, Field


class ManagementDecisionRecord(BaseModel):
    item_id: str = Field(min_length=1)
    decision: Literal["GO", "PAUSE", "REVIEW"]
    reviewer_id: str = Field(min_length=1)
    reviewer_type: Literal["human", "model", "system", "unknown"] = "unknown"
    rationale: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    follow_up_notes: list[str] = Field(default_factory=list)
    approved_next_action: str = ""
    decided_at: str | None = None
    related_project_id: str | None = None
    related_queue_item_id: str | None = None
    related_packet_id: str | None = None

