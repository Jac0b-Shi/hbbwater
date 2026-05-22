"""FastAPI main application."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.database import (
    ControlBase,
    ControlSessionLocal,
    activate_business_database,
    control_engine,
    dispose_databases,
    probe_business_database_path,
)
from app.routers import sensors, alerts, dashboard, config, account, auth, weather
from app.services.account import account_service
from app.services.business_profiles import ensure_business_profiles_bootstrap, profile_to_settings
from app.services.health_watchdog import (
    start_business_database_watchdog,
    start_memory_watchdog,
    stop_watchdog,
)
from app.services.weather import start_rainfall_collector


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print(f"[{datetime.utcnow()}] Flood Monitoring API starting up...")

    async with control_engine.begin() as conn:
        await conn.run_sync(ControlBase.metadata.create_all)

    async with ControlSessionLocal() as control_db:
        await account_service.ensure_bootstrap(control_db)
        profiles = await ensure_business_profiles_bootstrap(control_db)
        active_profile = next((profile for profile in profiles if profile.is_active), profiles[0])

    max_attempts = int(
        os.getenv("BUSINESS_DB_STARTUP_MAX_ATTEMPTS", os.getenv("DB_STARTUP_MAX_ATTEMPTS", "10"))
    )
    retry_delay = float(
        os.getenv("BUSINESS_DB_STARTUP_RETRY_DELAY_SECONDS", os.getenv("DB_STARTUP_RETRY_DELAY_SECONDS", "3"))
    )

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await activate_business_database(profile_to_settings(active_profile))
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            print(
                f"[{datetime.utcnow()}] Business database unavailable during startup "
                f"(attempt {attempt}/{max_attempts}), retrying in {retry_delay}s..."
            )
            await asyncio.sleep(retry_delay)

    if last_error is not None:
        print(
            f"[{datetime.utcnow()}] Business database startup deferred: {last_error}. "
            "Control-plane endpoints will remain available."
        )

    background_tasks = [
        task for task in (
            start_business_database_watchdog(),
            start_memory_watchdog(),
            start_rainfall_collector(),
        )
        if task is not None
    ]

    yield

    print(f"[{datetime.utcnow()}] Flood Monitoring API shutting down...")
    for background_task in background_tasks:
        await stop_watchdog(background_task)
    await dispose_databases()


app = FastAPI(
    title="Flood Monitoring API",
    description="校园水浸监测数据存储与可视化系统 API",
    version="1.0.0",
    lifespan=lifespan,
)

allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check():
    """Liveness check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "service": "flood-monitoring-api",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health/ready", tags=["health"])
async def readiness_check():
    """Readiness check that exercises the business database path."""
    timeout_seconds = float(os.getenv("BUSINESS_DB_READY_TIMEOUT_SECONDS", "5"))
    try:
        state = await asyncio.wait_for(probe_business_database_path(), timeout=timeout_seconds)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "service": "flood-monitoring-api",
                "error": str(exc),
                "timestamp": datetime.utcnow().isoformat(),
            },
        ) from exc

    return {
        "status": "ready",
        "version": "1.0.0",
        "service": "flood-monitoring-api",
        "business_database": state,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/", tags=["root"])
async def root():
    """API root endpoint."""
    return {
        "name": "Flood Monitoring API",
        "version": "1.0.0",
        "description": "校园水浸监测数据存储与可视化系统",
        "docs": "/docs",
        "health": "/health",
    }


app.include_router(sensors.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(weather.router, prefix="/api")


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
        log_level="info",
    )
