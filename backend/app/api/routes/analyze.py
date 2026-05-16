from fastapi import APIRouter, Depends, Request
from app.models.schemas import InputPayload, SimilarityResult
from app.services.ml_service import ml_engine
from app.services.otp_service import otp_service
from app.services.auto_decision import auto_decide
from app.core.db import db
from app.core.auth import verify_api_key
from app.core.limiter import limiter
import time
import uuid

router = APIRouter(dependencies=[Depends(verify_api_key)])


def _mask_sensitive(value: str, field_name: str) -> str:
    field_lower = field_name.lower()
    if any(t in field_lower for t in ("phone", "mobile", "contact", "card", "iban")):
        if len(value) > 4:
            return value[:2] + "*" * (len(value) - 4) + value[-2:]
        return "***"
    return value


@router.post("/analyze", response_model=SimilarityResult)
@limiter.limit("60/minute")
async def analyze_input(request: Request, payload: InputPayload):
    """FR-1/FR-2: Real-time field monitoring — rate limited to 60 req/min per IP."""
    start_time = time.time()
    result     = await ml_engine.evaluate_risk(payload.value, payload.behavior.dict(), category=payload.fieldName)
    latency_ms = (time.time() - start_time) * 1000

    alert_record = {
        "id":              str(uuid.uuid4()),
        "fieldName":       payload.fieldName,
        "value":           _mask_sensitive(payload.value, payload.fieldName),
        "formContext":     payload.formContext,
        "riskLevel":       result["riskLevel"],
        "similarityScore": result["similarityScore"],
        "latencyMs":       latency_ms,
        "behavior":        payload.behavior.dict(),
        "timestamp":       time.time(),
        "explanation":     result["message"],
        "status":          "monitored",
    }
    await db.insert_alert(alert_record)

    return SimilarityResult(
        riskLevel=result["riskLevel"],
        message=result["message"],
        similarityScore=result["similarityScore"],
        matchedValue=result["matchedValue"],
    )


@router.post("/submit")
@limiter.limit("10/minute")
async def submit_identity(request: Request, payload: InputPayload):
    """
    Final submission check with full 4-layer returning-user detection.

    Layer 1 — composite fingerprint exact match
    Layer 2 — approved-user semantic similarity
    Layer 3 — behavioral signature comparison
    Layer 4 — benefit history lookup
    """
    client_ip = request.client.host if request.client else "Unknown"
    platform  = payload.formContext or "Unknown"

    details           = payload.identityDetails or {"FullName": payload.value}
    # Merge top-level deviceId field into details so the fingerprint generator can use it.
    # The extension puts device_id inside identityDetails AND as a top-level deviceId field.
    device_id_from_payload = payload.deviceId or ""
    if device_id_from_payload and "device_id" not in details:
        details = {**details, "device_id": device_id_from_payload}
    details_with_meta = {**details, "platform": platform}

    # Extract identity signals for 4-layer checks
    phone_val = details.get("PhoneNumber", "").strip()
    email_val = details.get("EmailAddress", "").strip()
    device_id = details.get("device_id", device_id_from_payload).strip()

    # ── OTP phone verification gate ───────────────────────────────────────────
    # Required when a phone number is submitted. Consumes the token (single-use).
    if phone_val:
        otp_token = payload.otpToken or ""
        if not otp_token:
            return {
                "status":  "rejected",
                "message": "Phone number verification required. Please verify your phone with OTP before submitting.",
            }
        token_result = otp_service.consume_token(otp_token)
        if not token_result["valid"]:
            return {
                "status":  "rejected",
                "message": "Phone verification expired or already used. Please re-verify your phone number.",
            }
        # Cross-check: the token must belong to the submitted phone
        if token_result["phone_hash"] != ml_engine.phone_hash(phone_val):
            return {
                "status":  "rejected",
                "message": "Phone number does not match the verified number. Please re-verify.",
            }

    # ── Layer 1+2+general: composite ML risk evaluation ──────────────────────
    ml_result = await ml_engine.evaluate_composite_risk(details_with_meta, new_ip=client_ip)
    fingerprint = ml_result.get("fingerprint", "")

    # ── Layer 3: Behavioral comparison against stored profile ─────────────────
    behavior       = payload.behavior.dict()
    new_cps        = float(behavior.get("cps", 0))
    new_paste      = int(behavior.get("pastesCount", 0)) > 0
    behavioral_sig = ml_engine.compare_behavioral_signature(fingerprint, new_cps, new_paste)

    # Attach behavioral signals to ml_result so auto_decide and LLM can use them
    ml_result["behavioral_match_score"] = behavioral_sig.get("behavioral_match_score")
    ml_result["behavioral_note"]        = behavioral_sig.get("note", "")

    # Behavioral mismatch escalation:
    #   MEDIUM → HIGH  : confident mismatch (score < 0.4) on an already-suspicious submission
    #   LOW → MEDIUM   : profile exists but typing is very different — warrants closer look.
    #                    Without this, a returning user who changed all identity fields
    #                    (no FAISS match → LOW) but types identically/differently would
    #                    slip through as auto-approved despite having a behavioral history.
    beh_score = behavioral_sig.get("behavioral_match_score")
    if beh_score is not None:
        if beh_score < 0.4 and ml_result.get("riskLevel") == "MEDIUM":
            ml_result["riskLevel"] = "HIGH"
            ml_result["message"]  += f" | Behavioral mismatch: score {beh_score:.2f}."
        elif beh_score < 0.4 and ml_result.get("riskLevel") == "LOW":
            # Profile exists (beh_score is not None) but behaviour is very different —
            # escalate to MEDIUM so the LLM reviews rather than auto-approving.
            ml_result["riskLevel"] = "MEDIUM"
            ml_result["message"]  += f" | Behavioral anomaly on low-risk submission: score {beh_score:.2f}."

    # ── Layer 4: Benefit history lookup ──────────────────────────────────────
    # Map formContext (Edtech, Insurance, Jobs, Ecommerce) to a benefit_type + sector.
    benefit_type, sector = _infer_benefit(platform)
    benefit_check = await db.check_benefit_claimed(fingerprint, benefit_type, sector)
    benefit_claimed = benefit_check["already_claimed"]

    # ── Auto-decision engine ──────────────────────────────────────────────────
    decision = await auto_decide(
        ml_result,
        behavior,
        platform,
        benefit_claimed=benefit_claimed,
    )

    base_record = {
        "id":              str(uuid.uuid4()),
        "fieldName":       payload.fieldName,
        "value":           _mask_sensitive(payload.value, payload.fieldName),
        "formContext":     platform,
        "riskLevel":       ml_result["riskLevel"],
        "similarityScore": ml_result["similarityScore"],
        "timestamp":       time.time(),
        "aiDecision":      decision["decision"],
        "aiReason":        decision["reason"],
        "autoDecided":     decision["auto"],
        "clientIp":        client_ip,
        # Returning-user signals stored for audit visibility
        "fingerprintMatch":   ml_result.get("fingerprint_match", False),
        "approvedNameSim":    ml_result.get("approved_name_sim",  0.0),
        "approvedEmailSim":   ml_result.get("approved_email_sim", 0.0),
        "behavioralScore":    beh_score,
        "benefitAlreadyClaimed": benefit_claimed,
        "behavior":           behavior,
        "fingerprint":        fingerprint,
    }

    # ── APPROVE — commit to all layers ────────────────────────────────────────
    if decision["decision"] == "APPROVE":
        case_id = base_record["id"]

        await ml_engine.add_identity(
            details_with_meta,
            platform=platform,
            timestamp=str(time.time()),
            ip=client_ip,
            user_id=case_id,
            behavior=behavior,
            precomputed_fingerprint=fingerprint,   # reuse — avoids recomputation + guarantees consistency
        )

        # Persist phone hash and device_id to MongoDB so they survive disk loss
        p_hash = ml_engine.phone_hash(phone_val) if phone_val else ""
        if p_hash:
            await db.add_phone_hash(p_hash)

        identity_record = {
            "id":                   case_id,
            "name":                 payload.value,
            "timestamp":            time.time(),
            "identity_fingerprint": fingerprint,   # Layer 1 stored in DB
            "phone_hash":           p_hash,        # Gap 2 fix: queryable phone field
        }
        await db.insert_identity(identity_record)

        # Layer 4 — record benefit claim
        if fingerprint and benefit_type:
            await db.record_benefit_claim({
                "id":                   str(uuid.uuid4()),
                "user_id":              case_id,
                "identity_fingerprint": fingerprint,
                "benefit_type":         benefit_type,
                "sector":               sector,
                "claimed_at":           time.time(),
            })

        await db.insert_alert({**base_record, "status": "auto_approved", "explanation": decision["reason"]})
        return {"status": "success", "message": "Identity registered successfully."}

    # ── REJECT — blocked, not committed ──────────────────────────────────────
    if decision["decision"] == "REJECT":
        await db.insert_alert({**base_record, "status": "auto_rejected", "explanation": decision["reason"]})
        return {
            "status":    "rejected",
            "message":   decision["reason"],
            "riskLevel": ml_result["riskLevel"],
        }

    # ── ESCALATE — human officer decides ─────────────────────────────────────
    review_case = {
        **base_record,
        "status":          "pending",
        "identityDetails": details,
        "explanation":     ml_result["message"],
        "aiReason":        decision["reason"],
    }
    await db.insert_review_case(review_case)
    await db.insert_alert({**base_record, "status": "escalated_for_review", "explanation": decision["reason"]})
    return {
        "status":    "pending_review",
        "message":   "Your submission requires additional review. You will be contacted shortly.",
        "riskLevel": ml_result["riskLevel"],
        "caseId":    base_record["id"],
    }


def _infer_benefit(platform: str) -> tuple[str, str]:
    """
    Map the platform/formContext to a (benefit_type, sector) pair for Layer 4.
    Extend this table as new platforms are added.
    """
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
    # Default — use platform name as both
    clean = p.replace("-", "_").replace(" ", "_")[:30]
    return clean, clean
