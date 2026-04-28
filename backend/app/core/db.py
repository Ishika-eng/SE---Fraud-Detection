from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
import logging
from pymongo.errors import ServerSelectionTimeoutError

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.in_memory_alerts        = []
        self.in_memory_identities    = []
        self.in_memory_review_queue  = []
        self.in_memory_audit_logs    = []
        self.in_memory_benefit_claims = []   # Layer 4
        self.in_memory_phone_hashes  = []   # Gap 1 fix
        self.in_memory_device_ids    = []   # device-only registry
        self.use_fallback = False

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=2000)
            await self.client.server_info()
            self.db = self.client[settings.DATABASE_NAME]
            await self._ensure_indexes()
            logger.info("Successfully connected to MongoDB.")
        except ServerSelectionTimeoutError:
            logger.warning("MongoDB offline. Falling back to IN-MEMORY storage.")
            self.use_fallback = True

    async def _ensure_indexes(self):
        """Create indexes on first connect for performance."""
        try:
            await self.db.users.create_index("identity_fingerprint")
            await self.db.benefit_claims.create_index("identity_fingerprint")
            await self.db.benefit_claims.create_index([("identity_fingerprint", 1), ("benefit_type", 1), ("sector", 1)])
            await self.db.phone_hashes.create_index("hash", unique=True)
            await self.db.device_ids.create_index("device_id", unique=True)
            await self.db.identities.create_index("phone_hash")
        except Exception as e:
            logger.warning(f"Index creation skipped: {e}")

    async def disconnect(self):
        if self.client:
            self.client.close()

    # ── Alerts ────────────────────────────────────────────────────────────────

    async def insert_alert(self, alert_data: dict):
        if self.use_fallback:
            self.in_memory_alerts.append(alert_data)
        else:
            await self.db.alerts.insert_one(alert_data)
        return True

    async def get_recent_alerts(self, limit: int = 50, risk_level: str = None, search: str = None):
        if self.use_fallback:
            results = sorted(self.in_memory_alerts, key=lambda x: x.get("timestamp", 0), reverse=True)
            if risk_level:
                results = [r for r in results if r.get("riskLevel") == risk_level]
            if search:
                s = search.lower()
                results = [r for r in results if s in str(r.get("value", "")).lower()
                           or s in str(r.get("fieldName", "")).lower()]
            return results[:limit]
        else:
            query = {}
            if risk_level:
                query["riskLevel"] = risk_level
            if search:
                query["$or"] = [
                    {"value":     {"$regex": search, "$options": "i"}},
                    {"fieldName": {"$regex": search, "$options": "i"}},
                ]
            cursor = self.db.alerts.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
            return [doc async for doc in cursor]

    # ── Identities ────────────────────────────────────────────────────────────

    async def insert_identity(self, identity_data: dict):
        """
        Stores an approved identity record.
        identity_data should include identity_fingerprint if available.
        """
        if self.use_fallback:
            self.in_memory_identities.append(identity_data)
        else:
            await self.db.identities.insert_one(identity_data)
        return True

    async def get_identity_by_fingerprint(self, fingerprint: str) -> dict | None:
        """Layer 1: look up an approved user by composite fingerprint."""
        if self.use_fallback:
            return next(
                (i for i in self.in_memory_identities if i.get("identity_fingerprint") == fingerprint),
                None
            )
        else:
            doc = await self.db.identities.find_one({"identity_fingerprint": fingerprint}, {"_id": 0})
            return doc

    # ── Review Queue (SR-1, SR-2, BR-4) ──────────────────────────────────────

    async def insert_review_case(self, case_data: dict):
        if self.use_fallback:
            self.in_memory_review_queue.append(case_data)
        else:
            await self.db.review_queue.insert_one(case_data)
        return True

    async def get_review_queue(self, status: str = "pending"):
        if self.use_fallback:
            results = [c for c in self.in_memory_review_queue if c.get("status") == status]
            return sorted(results, key=lambda x: x.get("timestamp", 0), reverse=True)
        else:
            cursor = self.db.review_queue.find({"status": status}, {"_id": 0}).sort("timestamp", -1)
            return [doc async for doc in cursor]

    async def update_review_case(self, case_id: str, new_status: str, officer_note: str = ""):
        if self.use_fallback:
            for case in self.in_memory_review_queue:
                if case.get("id") == case_id:
                    case["status"]      = new_status
                    case["officerNote"] = officer_note
                    return True
            return False
        else:
            result = await self.db.review_queue.update_one(
                {"id": case_id},
                {"$set": {"status": new_status, "officerNote": officer_note}}
            )
            return result.modified_count > 0

    # ── Audit Log (FR-28, BR-6) ───────────────────────────────────────────────

    async def insert_audit_log(self, log_data: dict):
        """Immutable audit trail — never updated or deleted."""
        if self.use_fallback:
            self.in_memory_audit_logs.append(log_data)
        else:
            await self.db.audit_logs.insert_one(log_data)
        return True

    async def get_audit_logs(self, limit: int = 100):
        if self.use_fallback:
            return sorted(self.in_memory_audit_logs, key=lambda x: x.get("timestamp", 0), reverse=True)[:limit]
        else:
            cursor = self.db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
            return [doc async for doc in cursor]

    # ── Device IDs ───────────────────────────────────────────────────────────

    async def add_device_id(self, device_id: str):
        if self.use_fallback:
            if device_id not in self.in_memory_device_ids:
                self.in_memory_device_ids.append(device_id)
        else:
            try:
                await self.db.device_ids.update_one(
                    {"device_id": device_id},
                    {"$setOnInsert": {"device_id": device_id}},
                    upsert=True,
                )
            except Exception as e:
                logger.warning(f"Failed to persist device_id: {e}")

    async def load_device_ids(self) -> set:
        if self.use_fallback:
            return set(self.in_memory_device_ids)
        cursor = self.db.device_ids.find({}, {"_id": 0, "device_id": 1})
        return {doc["device_id"] async for doc in cursor}

    # ── Phone Hashes ─────────────────────────────────────────────────────────

    async def add_phone_hash(self, phone_hash: str):
        """Persist a phone hash to MongoDB (upsert — safe to call multiple times)."""
        if self.use_fallback:
            if phone_hash not in self.in_memory_phone_hashes:
                self.in_memory_phone_hashes.append(phone_hash)
        else:
            try:
                await self.db.phone_hashes.update_one(
                    {"hash": phone_hash},
                    {"$setOnInsert": {"hash": phone_hash}},
                    upsert=True,
                )
            except Exception as e:
                logger.warning(f"Failed to persist phone hash: {e}")

    async def load_phone_hashes(self) -> set:
        """Load all stored phone hashes — called on startup to hydrate ml_engine."""
        if self.use_fallback:
            return set(self.in_memory_phone_hashes)
        cursor = self.db.phone_hashes.find({}, {"_id": 0, "hash": 1})
        return {doc["hash"] async for doc in cursor}

    async def load_identity_fingerprints(self) -> dict:
        """Load all approved identity fingerprints — called on startup to hydrate ml_engine."""
        if self.use_fallback:
            return {i["identity_fingerprint"]: i["id"]
                    for i in self.in_memory_identities
                    if i.get("identity_fingerprint")}
        cursor = self.db.identities.find(
            {"identity_fingerprint": {"$exists": True, "$ne": ""}},
            {"_id": 0, "identity_fingerprint": 1, "id": 1}
        )
        return {doc["identity_fingerprint"]: doc["id"] async for doc in cursor}

    # ── Layer 4: Benefit Claims ───────────────────────────────────────────────

    async def record_benefit_claim(self, claim_data: dict):
        """
        Record a benefit claim after APPROVE.
        claim_data must include:
          id, user_id, identity_fingerprint, benefit_type, sector, claimed_at
        """
        if self.use_fallback:
            self.in_memory_benefit_claims.append(claim_data)
        else:
            await self.db.benefit_claims.insert_one(claim_data)
        return True

    async def check_benefit_claimed(self, fingerprint: str, benefit_type: str, sector: str) -> dict:
        """
        Layer 4: Check if a benefit was already claimed by this identity.
        Returns {"already_claimed": bool, "original_claim": dict | None}
        """
        if not fingerprint:
            return {"already_claimed": False, "original_claim": None}

        if self.use_fallback:
            existing = next(
                (
                    c for c in self.in_memory_benefit_claims
                    if c.get("identity_fingerprint") == fingerprint
                    and c.get("benefit_type")        == benefit_type
                    and c.get("sector")              == sector
                ),
                None,
            )
            return {"already_claimed": existing is not None, "original_claim": existing}
        else:
            doc = await self.db.benefit_claims.find_one(
                {
                    "identity_fingerprint": fingerprint,
                    "benefit_type":         benefit_type,
                    "sector":               sector,
                },
                {"_id": 0},
            )
            return {"already_claimed": doc is not None, "original_claim": doc}

    async def get_benefit_claims(self, fingerprint: str) -> list:
        """Return all benefit claims tied to an identity fingerprint."""
        if self.use_fallback:
            return [c for c in self.in_memory_benefit_claims
                    if c.get("identity_fingerprint") == fingerprint]
        else:
            cursor = self.db.benefit_claims.find({"identity_fingerprint": fingerprint}, {"_id": 0})
            return [doc async for doc in cursor]


db = DatabaseManager()
