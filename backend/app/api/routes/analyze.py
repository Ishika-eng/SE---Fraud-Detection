from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import InputPayload, SimilarityResult
from app.services.ml_service import ml_engine
from app.core.db import db
from app.core.auth import verify_api_key
import time
import uuid

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _mask_sensitive(value: str, field_name: str) -> str:
    """Mask GovID-like values before writing to logs/DB."""
    field_lower = field_name.lower()
    if any(t in field_lower for t in ("gov", "id", "ssn", "aadhaar", "pan", "passport")):
        if len(value) > 4:
            return value[:2] + "*" * (len(value) - 4) + value[-2:]
        return "***"
    return value


@router.post("/analyze", response_model=SimilarityResult)
async def analyze_input(payload: InputPayload):
    """
    REAL-TIME MONITORING: Visible on Dashboard.
    """
    start_time = time.time()
    # UNIFIED RISK SCORING: Identity + Behavior
    result = ml_engine.evaluate_risk(payload.value, payload.behavior.dict(), category=payload.fieldName)
    latency_ms = (time.time() - start_time) * 1000

    # MONITORING LOG (Always stored for the dashboard)
    alert_record = {
        "id": str(uuid.uuid4()),
        "fieldName": payload.fieldName,
        "value": _mask_sensitive(payload.value, payload.fieldName),
        "formContext": payload.formContext,
        "riskLevel": result["riskLevel"],
        "similarityScore": result["similarityScore"],
        "latencyMs": latency_ms,
        "behavior": payload.behavior.dict(),
        "timestamp": time.time(),
        "explanation": result["message"], # New field for detailed reasoning
        "status": "monitored"
    }
    await db.insert_alert(alert_record)

    return SimilarityResult(
        riskLevel=result["riskLevel"],
        message=result["message"], # This now contains the explanation
        similarityScore=result["similarityScore"],
        matchedValue=result["matchedValue"]
    )

@router.post("/submit")
async def submit_identity(payload: InputPayload):
    """
    FINAL SUBMISSION: Only unique data enters the IDENTITIES registry.
    """
    # COMPOSITE CHECK: Check Name + Email + GovID
    details = payload.identityDetails or {"FullName": payload.value}
    result = ml_engine.evaluate_composite_risk(details)
    
    # 1. LOG THE ATTEMPT FOR THE MONITORING DASHBOARD
    attempt_record = {
        "id": str(uuid.uuid4()),
        "fieldName": payload.fieldName,
        "value": _mask_sensitive(payload.value, payload.fieldName),
        "formContext": payload.formContext,
        "riskLevel": result["riskLevel"],
        "similarityScore": result["similarityScore"],
        "timestamp": time.time(),
        "status": "submit_attempt"
    }
    await db.insert_alert(attempt_record)

    if result["riskLevel"] == "HIGH":
        raise HTTPException(status_code=400, detail=f"Submission rejected: {result['message']}")

    # 2. COMMIT TO ML INDEX (Full composite bundle)
    ml_engine.add_identity(details)

    # 3. COMMIT TO THE 'OFFICIAL' IDENTITIES DATABASE
    official_identity = {
        "id": str(uuid.uuid4()),
        "name": payload.value,
        "timestamp": time.time()
    }
    # This officially populates the identities collection!
    await db.insert_identity(official_identity)

    return {"status": "success", "message": "Identity registered successfully"}

@router.get("/alerts")
async def get_alerts(limit: int = 50):
    return await db.get_recent_alerts(limit=limit)
