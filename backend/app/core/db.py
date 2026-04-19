from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
import logging
from pymongo.errors import ServerSelectionTimeoutError

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        # Fallback in-memory storage 
        self.in_memory_alerts = []
        self.in_memory_identities = []
        self.use_fallback = False

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=2000)
            await self.client.server_info()
            self.db = self.client[settings.DATABASE_NAME]
            logger.info("Successfully connected to MongoDB.")
        except ServerSelectionTimeoutError:
            logger.warning("MongoDB is offline at localhost. Falling back to IN-MEMORY storage for demo!")
            self.use_fallback = True
            
    async def disconnect(self):
        if self.client:
            self.client.close()

    async def insert_alert(self, alert_data):
        if self.use_fallback:
            self.in_memory_alerts.append(alert_data)
        else:
            await self.db.alerts.insert_one(alert_data)
        return True

    async def insert_identity(self, identity_data):
        if self.use_fallback:
            self.in_memory_identities.append(identity_data)
        else:
            await self.db.identities.insert_one(identity_data)
        return True

    async def get_recent_alerts(self, limit=50):
        if self.use_fallback:
            return sorted(self.in_memory_alerts, key=lambda x: x.get('timestamp', 0), reverse=True)[:limit]
        else:
            cursor = self.db.alerts.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
            return [doc async for doc in cursor]

db = DatabaseManager()
