from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class BehaviorMetrics(BaseModel):
    keystrokesCount: int = 0
    deletionsCount: int = 0
    pastesCount: int = 0
    timeToCompleteMs: float = 0.0
    cps: float = 0.0

class InputPayload(BaseModel):
    formContext: str = "unknown"
    fieldName: str
    value: str
    behavior: BehaviorMetrics
    identityDetails: Optional[Dict[str, str]] = None # New composite bundle for final submission
    sourceUrl: Optional[str] = None

class SimilarityResult(BaseModel):
    riskLevel: str
    message: str
    similarityScore: float
    matchedValue: Optional[str] = None
