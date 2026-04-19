from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.db import db
from app.api.routes import analyze

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for real-time form behavioral monitoring and similarity matching",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# App Lifecycle
@app.on_event("startup")
async def startup_db_client():
    await db.connect()

@app.on_event("shutdown")
async def shutdown_db_client():
    await db.disconnect()

# Register Routers
app.include_router(analyze.router, prefix="/api", tags=["Monitoring & Inference"])

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Real-Time Fraud Detection API is running"}

@app.get("/debug/db")
async def debug_db():
    if db.use_fallback:
        return {"mode": "in-memory", "alerts_count": len(db.in_memory_alerts), "identities_count": len(db.in_memory_identities)}
    
    collections = await db.db.list_collection_names()
    return {"mode": "mongodb", "collections": collections}
