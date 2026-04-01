from pydantic import BaseModel, Field


class TrendEvidence(BaseModel):
    source: str
    title: str
    url: str | None = None
    published_at: str | None = None
    snippet: str = ""


class TrendCandidate(BaseModel):
    name: str
    description: str
    evidence: list[TrendEvidence] = Field(default_factory=list)
    freshness: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    adoption_note: str


class TrendAnalysisRequest(BaseModel):
    trend_topic: str
    context: str | None = None
    max_items: int = Field(default=3, ge=1, le=10)


class TrendAnalysisResult(BaseModel):
    provider: str
    trend_topic: str
    candidate_trends: list[TrendCandidate] = Field(default_factory=list)


class TrendWorkflowReport(BaseModel):
    provider: str
    provider_hint: str
    trend_topic: str
    candidate_trends: list[TrendCandidate] = Field(default_factory=list)
    governance_note: str
    next_action_suggestion: str
