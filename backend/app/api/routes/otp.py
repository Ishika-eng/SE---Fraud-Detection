from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.services.otp_service import otp_service
from app.services.ml_service import ml_engine
from app.core.auth import verify_api_key

router = APIRouter(dependencies=[Depends(verify_api_key)])


class SendOTPRequest(BaseModel):
    phone: str


class VerifyOTPRequest(BaseModel):
    phone: str
    code: str


@router.post("/otp/send")
async def send_otp(body: SendOTPRequest):
    phone = body.phone.strip()
    normalized = ml_engine._normalize_phone(phone)
    if len(normalized) < 10:
        return {"success": False, "error": "Enter a valid 10-digit phone number."}

    phone_hash = ml_engine.phone_hash(phone)
    otp = otp_service.generate(phone_hash)

    masked = phone[-4:].rjust(len(phone), "*")

    # In production: send via SMS provider (Twilio / MSG91 / AWS SNS).
    # For demo: return OTP in the response so the UI can auto-fill it.
    return {
        "success": True,
        "otp":     otp,          # remove this field in production
        "message": f"OTP sent to {masked}. Valid for 5 minutes.",
    }


@router.post("/otp/verify")
async def verify_otp(body: VerifyOTPRequest):
    phone_hash = ml_engine.phone_hash(body.phone.strip())
    result = otp_service.verify(phone_hash, body.code)
    return result
