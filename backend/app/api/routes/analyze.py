from fastapi import APIRouter, Depends, Request
from app.models.schemas import InputPayload, SimilarityResult
from app.services.ml_service import ml_engine
from app.core.db import db
from app.core.auth import verify_api_key
from app.core.limiter import limiter
import time
import uuid

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _mask_sensitive(value: str, field_name: str) -> str:
    field_lower = field_name.lower()
    if any(t in field_lower for t in ("gov", "id", "ssn", "aadhaar", "pan", "passport")):
        if len(value) > 4:
            return value[:2] + "*" * (len(value) - 4) + value[-2:]
        return "***"
    return value


@router.post("/analyze", response_model=SimilarityResult)
@limiter.limit("60/minute")
async def analyze_input(request: Request, payload: InputPayload):
    """FR-1/FR-2: Real-time field monitoring — rate limited to 60 req/min per IP."""
    start_time = time.time()
    result = await ml_engine.evaluate_risk(payload.value, payload.behavior.dict(), category=payload.fieldName)
    latency_ms = (time.time() - start_time) * 1000

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
        "explanation": result["message"],
        "status": "monitored"
    }
    await db.insert_alert(alert_record)

    return SimilarityResult(
        riskLevel=result["riskLevel"],
        message=result["message"],
        similarityScore=result["similarityScore"],
        matchedValue=result["matchedValue"]
    )


@router.post("/submit")
@limiter.limit("10/minute")
async def submit_identity(request: Request, payload: InputPayload):
    """
    Final submission check.
    SR-1/SR-2/BR-4: HIGH risk → officer review queue, NOT auto-rejected.
    LOW/MEDIUM → identity committed immediately.
    """
    details = payload.identityDetails or {"FullName": payload.value}
    result = await ml_engine.evaluate_composite_risk(details)

    base_record = {
        "id": str(uuid.uuid4()),
        "fieldName": payload.fieldName,
        "value": _mask_sensitive(payload.value, payload.fieldName),
        "formContext": payload.formContext,
        "riskLevel": result["riskLevel"],
        "similarityScore": result["similarityScore"],
        "timestamp": time.time(),
    }

    if result["riskLevel"] == "HIGH":
        # Queue for officer review — never auto-reject (SR-1)
        review_case = {
            **base_record,
            "status": "pending",
            "identityDetails": details,
            "explanation": result["message"],
        }
        await db.insert_review_case(review_case)
        await db.insert_alert({**base_record, "status": "flagged_for_review", "explanation": result["message"]})

        return {
            "status": "pending_review",
            "message": "Your submission has been flagged for officer review. You will be contacted shortly.",
            "riskLevel": "HIGH",
            "caseId": base_record["id"]
        }

    if result["riskLevel"] == "MEDIUM":
        # MEDIUM risk: log and queue for soft review — do NOT commit to index to prevent registry poisoning
        review_case = {
            **base_record,
            "status": "pending",
            "identityDetails": details,
            "explanation": result["message"],
        }
        await db.insert_review_case(review_case)
        await db.insert_alert({**base_record, "status": "flagged_for_review", "explanation": result["message"]})

        return {
            "status": "pending_review",
            "message": "Your submission is under review. You will be contacted if additional verification is needed.",
            "riskLevel": "MEDIUM",
            "caseId": base_record["id"]
        }

    # LOW risk only — safe to commit to index
    await ml_engine.add_identity(details)
    await db.insert_identity({"id": base_record["id"], "name": payload.value, "timestamp": time.time()})
    await db.insert_alert({**base_record, "status": "submit_approved"})

    return {"status": "success", "message": "Identity registered successfully"}
