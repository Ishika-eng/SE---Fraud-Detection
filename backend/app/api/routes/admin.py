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
    """FR-27: CSV export of alerts including returning-user signals."""
    alerts = await db.get_recent_alerts(limit=1000, risk_level=risk_level, search=search)

    fieldnames = [
        "id", "fieldName", "value", "riskLevel", "similarityScore",
        "timestamp", "status",
        # Returning-user columns (may be absent on older records)
        "fingerprintMatch", "approvedNameSim", "approvedEmailSim",
        "behavioralScore",  "benefitAlreadyClaimed",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for a in alerts:
        writer.writerow({k: a.get(k, "") for k in fieldnames})

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
    """
    Officer approves → identity committed to ALL 4 layers:

      Layer 1 — composite fingerprint stored
      Layer 2 — name + email added to approved-only FAISS index
      Layer 3 — behavioral profile initialised / updated
      Layer 4 — benefit claim recorded
    """
    queue = await db.get_review_queue(status="pending")
    case  = next((c for c in queue if c.get("id") == case_id), None)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found in pending queue")

    identity_details = case.get("identityDetails", {})
    behavior         = case.get("behavior", {})
    platform         = case.get("formContext", "Unknown")
    fingerprint      = case.get("fingerprint", "")

    # Commit to ML engine (Layers 1, 2, 3 handled inside add_identity)
    if identity_details:
        await ml_engine.add_identity(
            identity_details,
            platform=platform,
            timestamp=str(time.time()),
            ip=case.get("clientIp", ""),
            user_id=case_id,
            behavior=behavior,
        )

    # Store approved identity in DB (with fingerprint for Layer 1 DB-side lookup)
    await db.insert_identity({
        "id":                   case_id,
        "name":                 case.get("value", ""),
        "timestamp":            time.time(),
        "identity_fingerprint": fingerprint,
    })

    # Layer 4 — record benefit claim on officer approval too
    if fingerprint:
        phone_val = identity_details.get("PhoneNumber", "")
        email_val = identity_details.get("EmailAddress", "")
        device_id = identity_details.get("device_id", "")
        # Recompute fingerprint if not stored on case (backward compat)
        fp = fingerprint or ml_engine.generate_identity_fingerprint(phone_val, email_val, device_id)

        benefit_type, sector = _infer_benefit(platform)
        if benefit_type:
            existing = await db.check_benefit_claimed(fp, benefit_type, sector)
            if not existing["already_claimed"]:
                await db.record_benefit_claim({
                    "id":                   str(uuid.uuid4()),
                    "user_id":              case_id,
                    "identity_fingerprint": fp,
                    "benefit_type":         benefit_type,
                    "sector":               sector,
                    "claimed_at":           time.time(),
                })

    await db.update_review_case(case_id, "approved", body.officer_note)
    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "approve", "case_id": case_id,
        "officer": officer, "note": body.officer_note, "timestamp": time.time()
    })
    return {"status": "approved"}


@router.post("/review-queue/{case_id}/reject")
async def reject_case(case_id: str, body: ReviewDecision, officer: str = Depends(verify_dashboard_token)):
    """Officer rejects → identity is NOT added to any registry."""
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
        "high_risk_threshold":   ml_engine.high_threshold,
        "medium_risk_threshold": ml_engine.medium_threshold,
        "bot_cps_threshold":     ml_engine.bot_cps_threshold,
        "device_max_attempts":   ml_engine.device_max_attempts,
        "device_window_minutes": int(ml_engine.device_window_seconds / 60),
    }


class ThresholdUpdate(BaseModel):
    high_risk_threshold:   float
    medium_risk_threshold: float
    bot_cps_threshold:     float = None
    device_max_attempts:   int   = None
    device_window_minutes: int   = None


@router.put("/thresholds")
async def update_thresholds(body: ThresholdUpdate, officer: str = Depends(verify_dashboard_token)):
    if not (0 < body.medium_risk_threshold < body.high_risk_threshold <= 100):
        raise HTTPException(status_code=400, detail="medium_risk_threshold must be less than high_risk_threshold")
    if body.bot_cps_threshold is not None and body.bot_cps_threshold <= 0:
        raise HTTPException(status_code=400, detail="bot_cps_threshold must be positive")
    if body.device_max_attempts is not None and body.device_max_attempts < 1:
        raise HTTPException(status_code=400, detail="device_max_attempts must be at least 1")
    if body.device_window_minutes is not None and body.device_window_minutes < 1:
        raise HTTPException(status_code=400, detail="device_window_minutes must be at least 1")

    settings.HIGH_RISK_THRESHOLD   = body.high_risk_threshold
    settings.MEDIUM_RISK_THRESHOLD = body.medium_risk_threshold
    ml_engine.update_thresholds(
        body.high_risk_threshold,
        body.medium_risk_threshold,
        body.bot_cps_threshold,
        body.device_max_attempts,
        body.device_window_minutes,
    )

    await db.insert_audit_log({
        "id":               str(uuid.uuid4()),
        "action":           "update_thresholds",
        "high":             body.high_risk_threshold,
        "medium":           body.medium_risk_threshold,
        "bot_cps":          ml_engine.bot_cps_threshold,
        "device_max":       ml_engine.device_max_attempts,
        "device_window_min": int(ml_engine.device_window_seconds / 60),
        "officer":          officer,
        "timestamp":        time.time(),
    })
    return {
        "status":                "updated",
        "high_risk_threshold":   ml_engine.high_threshold,
        "medium_risk_threshold": ml_engine.medium_threshold,
        "bot_cps_threshold":     ml_engine.bot_cps_threshold,
        "device_max_attempts":   ml_engine.device_max_attempts,
        "device_window_minutes": int(ml_engine.device_window_seconds / 60),
    }


# ── Bulk Identity Import (registry seeding) ───────────────────────────────────

class IdentityRecord(BaseModel):
    FullName:     Optional[str] = ""
    EmailAddress: Optional[str] = ""
    GovID:        Optional[str] = ""
    PhoneNumber:  Optional[str] = ""


@router.post("/import")
async def bulk_import(records: List[IdentityRecord], officer: str = Depends(verify_dashboard_token)):
    """
    Seed the FAISS index with pre-existing registered identities (e.g. legacy DB migration).
    Records are added to BOTH the general and approved-user indices since they are
    pre-verified identities.
    """
    imported = 0
    for record in records:
        details = record.dict()
        if any(v for v in details.values()):
            # Use a stable deterministic user_id so fingerprints are consistent
            user_id = f"imported-{uuid.uuid5(uuid.NAMESPACE_OID, str(details))}"
            await ml_engine.add_identity(
                details,
                platform="bulk_import",
                timestamp=str(time.time()),
                user_id=user_id,
            )
            imported += 1

    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "bulk_import",
        "count": imported, "officer": officer, "timestamp": time.time()
    })
    return {"status": "success", "imported": imported}


# ── Velocity Reset (demo / ops tool) ─────────────────────────────────────────

@router.post("/velocity/reset")
async def reset_velocity(officer: str = Depends(verify_dashboard_token)):
    """Clear all in-memory device velocity counters (useful for demos and testing)."""
    ml_engine.device_submission_times.clear()
    await db.insert_audit_log({
        "id": str(uuid.uuid4()), "action": "velocity_reset",
        "officer": officer, "timestamp": time.time()
    })
    return {"status": "cleared", "message": "All device velocity counters reset."}


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(limit: int = 100):
    return await db.get_audit_logs(limit=limit)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _infer_benefit(platform: str) -> tuple[str, str]:
    """Mirror of analyze.py benefit inference — kept in sync manually."""
    p = platform.lower()
    if "edtech" in p or "course" in p or "exam" in p:
        return "exam_slot",       "edtech"
    if "job" in p or "employ" in p or "recruit" in p:
        return "job_application", "jobs"
    if "insurance" in p or "claim" in p:
        return "insurance_claim", "insurance"
    if "ecommerce" in p or "shop" in p or "order" in p or "purchase" in p:
        return "first_purchase",  "ecommerce"
    if "gov" in p or "scheme" in p or "subsidy" in p or "benefit" in p:
        return "gov_benefit",     "government"
    clean = p.replace("-", "_").replace(" ", "_")[:30]
    return clean, clean
