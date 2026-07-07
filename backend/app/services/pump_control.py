from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.services.alerting import compare_threshold


@dataclass(frozen=True)
class PumpControlContext:
    sensor_id: str
    risk_level: str
    predicted_free_rise_mm: float
    predicted_observed_rise_mm: float
    pump_scenario_active: bool = False
    derived_pump_threshold_cm: float | None = None
    projected_distance_cm: float | None = None
    threshold_condition: str | None = None
    actuator_binding_id: str | None = None
    data_status: str = "available"


class PumpController(Protocol):
    """Adapter boundary for future PLC or MCU pump control implementations."""

    async def build_recommendation(self, context: PumpControlContext) -> dict[str, Any]:
        """Return a recommendation only; real start/stop execution is out of scope for V1."""


class NoopPumpController:
    """Default controller used until a concrete hardware channel is approved."""

    async def build_recommendation(self, context: PumpControlContext) -> dict[str, Any]:
        if context.data_status != "available" or context.risk_level == "unknown":
            return {
                "mode": "recommendation_only",
                "executable": False,
                "adapter": "noop",
                "action": "hold_manual_review",
                "sensor_id": context.sensor_id,
                "actuator_binding_id": context.actuator_binding_id,
                "reason": "DATA_DEGRADED",
            }

        pump_triggered = context.pump_scenario_active
        if (
            not pump_triggered
            and context.derived_pump_threshold_cm is not None
            and context.projected_distance_cm is not None
            and context.threshold_condition is not None
        ):
            pump_triggered = compare_threshold(
                context.projected_distance_cm,
                context.derived_pump_threshold_cm,
                context.threshold_condition,
            )

        should_prepare = context.risk_level in {"warning", "critical"} or pump_triggered
        return {
            "mode": "recommendation_only",
            "executable": False,
            "adapter": "noop",
            "action": "prepare_pump" if should_prepare else "none",
            "sensor_id": context.sensor_id,
            "actuator_binding_id": context.actuator_binding_id,
            "reason": (
                "预测水位压力可能需要排水泵介入，当前版本仅生成建议"
                if should_prepare
                else "预测水位压力未达到泵控建议阈值"
            ),
        }


def get_pump_controller() -> PumpController:
    return NoopPumpController()
