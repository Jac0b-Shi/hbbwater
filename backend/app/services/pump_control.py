from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PumpControlContext:
    sensor_id: str
    risk_level: str
    predicted_free_rise_mm: float
    predicted_observed_rise_mm: float
    pump_on_rise_mm: float
    actuator_binding_id: str | None = None


class PumpController(Protocol):
    """Adapter boundary for future PLC or MCU pump control implementations."""

    async def build_recommendation(self, context: PumpControlContext) -> dict[str, Any]:
        """Return a recommendation only; real start/stop execution is out of scope for V1."""


class NoopPumpController:
    """Default controller used until a concrete hardware channel is approved."""

    async def build_recommendation(self, context: PumpControlContext) -> dict[str, Any]:
        should_prepare = (
            context.risk_level in {"warning", "critical"}
            or context.predicted_free_rise_mm >= context.pump_on_rise_mm
        )
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
