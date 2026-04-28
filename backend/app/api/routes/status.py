from fastapi import APIRouter, HTTPException
from app.core.db import db
from app.core.limiter import limiter
from fastapi import Request

router = APIRouter()

STATUS_MESSAGES = {
    "pending":  "Your application is currently under review by a compliance officer. Please check back in 5–7 working days.",
    "approved": "Your registration has been approved. You are now enrolled in the scheme. Benefits will be credited to your registered bank account.",
    "rejected": "Your application could not be processed. This may be due to a duplicate identity or incomplete verification. Please visit your nearest Common Service Centre for assistance.",
}

@router.get("/status/{case_id}")
@limiter.limit("20/minute")
async def get_case_status(case_id: str, request: Request):
    """
    Public endpoint — no auth required.
    Returns only status + message. No identity details exposed.
    """
    if len(case_id) < 8:
        raise HTTPException(status_code=400, detail="Invalid reference number.")

    # Search across all statuses
    for status in ("pending", "approved", "rejected"):
        queue = await db.get_review_queue(status=status)
        case = next((c for c in queue if c.get("id") == case_id), None)
        if case:
            return {
                "ref": case_id[:8].upper(),
                "status": status,
                "message": STATUS_MESSAGES[status],
                "submitted_at": case.get("timestamp"),
            }

    raise HTTPException(status_code=404, detail="Reference number not found. Please check and try again.")
