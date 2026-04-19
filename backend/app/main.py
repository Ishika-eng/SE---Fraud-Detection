from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.db import db
from app.core.limiter import limiter
from app.api.routes import analyze
from app.api.routes import admin, auth_routes

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for real-time form fraud monitoring and similarity matching",
    version="1.0.0"
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — only known dashboard origins, never wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

# App lifecycle
@app.on_event("startup")
async def startup_db_client():
    await db.connect()

@app.on_event("shutdown")
async def shutdown_db_client():
    await db.disconnect()

# Extension routes (API key auth)
app.include_router(analyze.router, prefix="/api", tags=["Extension — Monitoring"])

# Dashboard routes (JWT auth)
app.include_router(admin.router, prefix="/api/admin", tags=["Dashboard — Admin"])

# Auth routes (no auth required)
app.include_router(auth_routes.router, prefix="/api/auth", tags=["Auth"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/debug/db")
async def debug_db():
    if db.use_fallback:
        return {
            "mode": "in-memory",
            "alerts": len(db.in_memory_alerts),
            "review_queue": len(db.in_memory_review_queue),
            "audit_logs": len(db.in_memory_audit_logs),
        }
    collections = await db.db.list_collection_names()
    return {"mode": "mongodb", "collections": collections}
