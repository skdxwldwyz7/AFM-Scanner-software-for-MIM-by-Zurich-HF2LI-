from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ApproachSignalConfig:
    device: str = ""
    channel: str = "ch1"
    quantity: str = "r"


@dataclass(slots=True)
class ApproachConditionConfig:
    condition_type: str = "above"
    threshold: float = 1.0
    low: float = 0.0
    high: float = 1.0
    baseline: float = 0.0
    consecutive: int = 3


@dataclass(slots=True)
class ApproachSafetyConfig:
    max_travel_um: float = 10.0
    max_steps: int = 1000
    retract_on_fail_um: float = 1.0


@dataclass(slots=True)
class ApproachConfig:
    name: str = "Generic approach"
    actuator: str = "mock.z"
    direction: str = "down"
    step_um: float = 0.05
    settle_s: float = 0.05
    signal: ApproachSignalConfig = field(default_factory=ApproachSignalConfig)
    condition: ApproachConditionConfig = field(default_factory=ApproachConditionConfig)
    safety: ApproachSafetyConfig = field(default_factory=ApproachSafetyConfig)


def evaluate_approach_condition(
    value: float,
    config: ApproachConditionConfig,
    *,
    baseline: float | None = None,
) -> bool:
    condition = config.condition_type.strip().lower()
    reference = config.baseline if baseline is None else baseline
    if condition == "above":
        return value >= config.threshold
    if condition == "below":
        return value <= config.threshold
    if condition == "between":
        return config.low <= value <= config.high
    if condition == "outside":
        return value < config.low or value > config.high
    if condition == "delta":
        return abs(value - reference) >= config.threshold
    raise ValueError(f"Unknown approach condition: {config.condition_type}")


__all__ = [
    "ApproachConfig",
    "ApproachConditionConfig",
    "ApproachSafetyConfig",
    "ApproachSignalConfig",
    "evaluate_approach_condition",
]
