from abc import ABC, abstractmethod

from app.schemas.trend import TrendAnalysisRequest, TrendAnalysisResult


class TrendProvider(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, request: TrendAnalysisRequest) -> TrendAnalysisResult:
        raise NotImplementedError

