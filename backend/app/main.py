"""FastAPI main application."""
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, DATABASE_DIALECT, engine, should_auto_create_schema
from app.routers import sensors, alerts, dashboard, config, account
from app.services.schema import ensure_runtime_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    print(f"[{datetime.utcnow()}] Flood Monitoring API starting up...")
    async with engine.begin() as conn:
        if should_auto_create_schema(DATABASE_DIALECT):
            await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)
    yield
    # Shutdown
    print(f"[{datetime.utcnow()}] Flood Monitoring API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Flood Monitoring API",
    description="校园水浸监测数据存储与可视化系统 API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "service": "flood-monitoring-api",
        "timestamp": datetime.utcnow().isoformat()
    }


# Root endpoint
@app.get("/", tags=["root"])
async def root():
    """API root endpoint."""
    return {
        "name": "Flood Monitoring API",
        "version": "1.0.0",
        "description": "校园水浸监测数据存储与可视化系统",
        "docs": "/docs",
        "health": "/health"
    }


# Include routers with /api prefix
app.include_router(sensors.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(account.router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )
