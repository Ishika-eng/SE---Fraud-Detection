from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
import logging
from pymongo.errors import ServerSelectionTimeoutError

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.in_memory_alerts = []
        self.in_memory_identities = []
        self.in_memory_review_queue = []
        self.in_memory_audit_logs = []
        self.use_fallback = False

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=2000)
            await self.client.server_info()
            self.db = self.client[settings.DATABASE_NAME]
            logger.info("Successfully connected to MongoDB.")
        except ServerSelectionTimeoutError:
            logger.warning("MongoDB offline. Falling back to IN-MEMORY storage.")
            self.use_fallback = True

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
                    {"value": {"$regex": search, "$options": "i"}},
                    {"fieldName": {"$regex": search, "$options": "i"}},
                ]
            cursor = self.db.alerts.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
            return [doc async for doc in cursor]

    # ── Identities ────────────────────────────────────────────────────────────

    async def insert_identity(self, identity_data: dict):
        if self.use_fallback:
            self.in_memory_identities.append(identity_data)
        else:
            await self.db.identities.insert_one(identity_data)
        return True

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
                    case["status"] = new_status
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


db = DatabaseManager()
