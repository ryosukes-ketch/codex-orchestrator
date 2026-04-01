from typing import Optional

from pydantic import BaseModel, Field


class ProjectBrief(BaseModel):
    title: Optional[str] = None
    objective: str
    scope: Optional[str] = None
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    deadline: Optional[str] = None
    stakeholders: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    raw_request: str


class IntakeResult(BaseModel):
    brief: ProjectBrief
    missing_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)

