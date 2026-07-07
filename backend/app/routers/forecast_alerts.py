"""Forecast-driven water level alert APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_control_db, get_db
from app.models import ForecastPredictionRun
from app.schemas import (
    ForecastAlertConfigResponse,
    ForecastAlertConfigUpdate,
    ForecastAlertEvaluateRequest,
    ForecastPredictionRunList,
    ForecastPredictionRunResponse,
)
from app.services.auth import require_roles
from app.services.forecast_alerts import (
    evaluate_forecast_alerts,
    list_forecast_alert_config,
    save_forecast_alert_global_config,
    upsert_forecast_alert_profiles,
)

router = APIRouter(prefix="/forecast-alerts", tags=["forecast-alerts"])
require_forecast_manager = require_roles("super_admin", "admin")


@router.get("/config", response_model=ForecastAlertConfigResponse)
async def get_forecast_alert_config(
    _: dict = Depends(require_forecast_manager),
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Return global forecast alert settings and per-sensor profiles."""
    return await list_forecast_alert_config(db, control_db)


@router.post("/config", response_model=ForecastAlertConfigResponse)
async def update_forecast_alert_config(
    payload: ForecastAlertConfigUpdate,
    _: dict = Depends(require_forecast_manager),
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Save forecast alert settings."""
    try:
        if payload.global_config is not None:
            await save_forecast_alert_global_config(
                control_db,
                payload.global_config.model_dump(exclude_unset=True),
                db=db,
            )
        await upsert_forecast_alert_profiles(
            db,
            [profile.model_dump() for profile in payload.profiles],
        )
        await db.flush()
        await control_db.flush()
        return await list_forecast_alert_config(db, control_db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/evaluate", response_model=ForecastPredictionRunResponse)
async def evaluate_forecast_alerts_now(
    payload: ForecastAlertEvaluateRequest,
    current_user: dict = Depends(require_forecast_manager),
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Run a manual forecast evaluation. Dry-run writes prediction rows but does not notify."""
    return await evaluate_forecast_alerts(
        db,
        control_db,
        dry_run=payload.dry_run,
        trigger_type="manual",
        sensor_ids=payload.sensor_ids,
        horizon_hours=payload.horizon_hours,
        created_by=current_user.get("username") or current_user.get("display_name"),
    )


@router.get("/latest", response_model=ForecastPredictionRunResponse | None)
async def get_latest_forecast_alert_run(
    _: dict = Depends(require_forecast_manager),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest forecast evaluation run."""
    return await db.scalar(
        select(ForecastPredictionRun)
        .options(selectinload(ForecastPredictionRun.results))
        .order_by(ForecastPredictionRun.created_at.desc())
        .limit(1)
    )


@router.get("/runs", response_model=ForecastPredictionRunList)
async def list_forecast_alert_runs(
    limit: int = Query(default=20, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    _: dict = Depends(require_forecast_manager),
    db: AsyncSession = Depends(get_db),
):
    """List forecast evaluation runs with their prediction results."""
    base_query = select(ForecastPredictionRun)
    total = await db.scalar(select(func.count()).select_from(ForecastPredictionRun))
    offset = (page - 1) * limit
    result = await db.execute(
        base_query
        .options(selectinload(ForecastPredictionRun.results))
        .order_by(ForecastPredictionRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": result.scalars().unique().all(),
        "total": int(total or 0),
        "page": page,
        "page_size": limit,
    }
