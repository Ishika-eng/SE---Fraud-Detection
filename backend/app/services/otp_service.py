import random
import time
import uuid
import logging

logger = logging.getLogger(__name__)

OTP_TTL   = 300   # 5 minutes
TOKEN_TTL = 600   # 10 minutes
MAX_ATTEMPTS = 3


class OTPService:
    def __init__(self):
        # phone_hash -> {otp, expires_at, attempts}
        self._pending: dict = {}
        # token -> {phone_hash, expires_at}
        self._tokens: dict = {}

    def generate(self, phone_hash: str) -> str:
        """Generate a 6-digit OTP for a phone hash and store it."""
        otp = str(random.randint(100000, 999999))
        self._pending[phone_hash] = {
            "otp":        otp,
            "expires_at": time.time() + OTP_TTL,
            "attempts":   0,
        }
        logger.info(f"OTP generated for hash {phone_hash[:8]}…")
        return otp

    def verify(self, phone_hash: str, code: str) -> dict:
        """
        Verify submitted OTP code against stored record.
        On success: removes pending record, issues a one-time verification token.
        """
        record = self._pending.get(phone_hash)
        if not record:
            return {"success": False, "error": "No OTP was sent for this number. Request one first."}

        if time.time() > record["expires_at"]:
            del self._pending[phone_hash]
            return {"success": False, "error": "OTP expired. Please request a new one."}

        record["attempts"] += 1
        if record["attempts"] > MAX_ATTEMPTS:
            del self._pending[phone_hash]
            return {"success": False, "error": "Too many incorrect attempts. Request a new OTP."}

        if record["otp"] != code.strip():
            remaining = MAX_ATTEMPTS - record["attempts"]
            return {"success": False, "error": f"Incorrect OTP. {remaining} attempt(s) left."}

        # Success — issue verification token
        del self._pending[phone_hash]
        token = str(uuid.uuid4())
        self._tokens[token] = {
            "phone_hash": phone_hash,
            "expires_at": time.time() + TOKEN_TTL,
        }
        logger.info(f"OTP verified for hash {phone_hash[:8]}… — token issued.")
        return {"success": True, "token": token}

    def consume_token(self, token: str) -> dict:
        """
        Validate and consume a verification token (single-use).
        Returns {valid, phone_hash}.
        """
        record = self._tokens.get(token)
        if not record:
            return {"valid": False, "phone_hash": None}
        if time.time() > record["expires_at"]:
            del self._tokens[token]
            return {"valid": False, "phone_hash": None}
        phone_hash = record["phone_hash"]
        del self._tokens[token]
        return {"valid": True, "phone_hash": phone_hash}


otp_service = OTPService()
