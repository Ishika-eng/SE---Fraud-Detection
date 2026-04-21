from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.core.security import verify_dashboard_token
from app.core.config import settings
from app.core.db import db
from app.services.ml_service import ml_engine
from pydantic import BaseModel
from typing import Optional, List
import time, uuid, io, csv

router = APIRouter(dependencies=[Depends(verify_dashboard_token)])


# ── Alerts (dashboard, with filters + export) ─────────────────────────────────

@router.get("/alerts")
async def get_alerts(limit: int = 50, risk_level: str = None, search: str = None):
    """FR-25: filterable alert list for dashboard."""
    return await db.get_recent_alerts(limit=limit, risk_level=risk_level, search=search)


@router.get("/alerts/export")
async def export_alerts(risk_level: str = None, search: str = None):
    """FR-27: CSV export of alerts."""
    alerts = await db.get_recent_alerts(limit=1000, risk_level=risk_level, search=search)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "fieldName", "value", "riskLevel", "similarityScore", "timestamp", "status"])
    writer.writeheader()
    for a in alerts:
        writer.writerow({k: a.get(k, "") for k in writer.fieldnames})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fraud_alerts.csv"}
    )


# ── Review Queue (SR-1, SR-2, BR-4) ──────────────────────────────────────────

@router.get("/review-queue")
async def get_review_queue(status: str = "pending"):
    return await db.get_review_queue(status=status)


class ReviewDecision(BaseModel):
    officer_note: Optional[str] = ""


@router.post("/review-queue/{case_id}/approve")
async def approve_case(case_id: str, body: ReviewDecision, officer: str = Depends(verify_dashboard_token)):
    """Officer approves → identity committed to ML index."""
    queue = await db.get_review_queue(status="pending")
    case = next((c for c in queue if c.get("id") == case_id), None)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found in pending queue")

    # Commit identity to FAISS
    if case.get("identityDetails"):
        await ml_engine.add_identity(case["identityDetails"])

    await db.update_review_case(case_id, "approved", body.officer_note)
    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "approve", "case_id": case_id,
        "officer": officer, "note": body.officer_note, "timestamp": time.time()
    })
    return {"status": "approved"}


@router.post("/review-queue/{case_id}/reject")
async def reject_case(case_id: str, body: ReviewDecision, officer: str = Depends(verify_dashboard_token)):
    """Officer rejects → identity is NOT added to the index."""
    updated = await db.update_review_case(case_id, "rejected", body.officer_note)
    if not updated:
        raise HTTPException(status_code=404, detail="Case not found")

    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "reject", "case_id": case_id,
        "officer": officer, "note": body.officer_note, "timestamp": time.time()
    })
    return {"status": "rejected"}


# ── Thresholds (FR-20, BR-2) ──────────────────────────────────────────────────

@router.get("/thresholds")
async def get_thresholds():
    return {
        "high_risk_threshold": settings.HIGH_RISK_THRESHOLD,
        "medium_risk_threshold": settings.MEDIUM_RISK_THRESHOLD,
    }


class ThresholdUpdate(BaseModel):
    high_risk_threshold: float
    medium_risk_threshold: float
    bot_cps_threshold: float = None  # Optional — defaults to current value if omitted


@router.put("/thresholds")
async def update_thresholds(body: ThresholdUpdate, officer: str = Depends(verify_dashboard_token)):
    if not (0 < body.medium_risk_threshold < body.high_risk_threshold <= 100):
        raise HTTPException(status_code=400, detail="medium_risk_threshold must be less than high_risk_threshold")
    if body.bot_cps_threshold is not None and body.bot_cps_threshold <= 0:
        raise HTTPException(status_code=400, detail="bot_cps_threshold must be positive")

    settings.HIGH_RISK_THRESHOLD = body.high_risk_threshold
    settings.MEDIUM_RISK_THRESHOLD = body.medium_risk_threshold
    ml_engine.update_thresholds(body.high_risk_threshold, body.medium_risk_threshold, body.bot_cps_threshold)

    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "update_thresholds",
        "high": body.high_risk_threshold, "medium": body.medium_risk_threshold,
        "bot_cps": ml_engine.bot_cps_threshold,
        "officer": officer, "timestamp": time.time()
    })
    return {
        "status": "updated",
        "high_risk_threshold": body.high_risk_threshold,
        "medium_risk_threshold": body.medium_risk_threshold,
        "bot_cps_threshold": ml_engine.bot_cps_threshold
    }


# ── Bulk Identity Import (registry seeding) ───────────────────────────────────

class IdentityRecord(BaseModel):
    FullName: Optional[str] = ""
    EmailAddress: Optional[str] = ""
    GovID: Optional[str] = ""


@router.post("/import")
async def bulk_import(records: List[IdentityRecord], officer: str = Depends(verify_dashboard_token)):
    """Seed the FAISS index with existing registered identities."""
    imported = 0
    for record in records:
        details = record.dict()
        if any(v for v in details.values()):
            ml_engine.add_identity(details)
            imported += 1

    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "bulk_import",
        "count": imported, "officer": officer, "timestamp": time.time()
    })
    return {"status": "success", "imported": imported}


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(limit: int = 100):
    return await db.get_audit_logs(limit=limit)
