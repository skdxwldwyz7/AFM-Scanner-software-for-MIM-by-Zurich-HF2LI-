"""Minimal FM-AFM AUX channel definitions shared by the GUI and adapter."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FMChannel:
    key: str
    label: str
    unit: str


FM_CHANNELS = (
    FMChannel("auxout1", "Aux Out 1 / X", "V"),
    FMChannel("auxout2", "Aux Out 2 / Y", "V"),
    FMChannel("auxout3", "Aux Out 3 / Z PID output", "V"),
    FMChannel("auxout4", "Aux Out 4 / PLL Δf output", "V"),
)
FM_CHANNEL_BY_KEY = {item.key: item for item in FM_CHANNELS}


class FMAcquisition:
    """Acquire only the four AUX output voltages; no PLL/PID safety reads."""

    def __init__(self, adapter: object) -> None:
        self.adapter = adapter

    def __call__(self, channels: tuple[str, ...]) -> dict[str, float]:
        sample = self.adapter.read_fm_snapshot(set(channels))
        missing = [key for key in channels if not math.isfinite(sample.get(key, math.nan))]
        if missing:
            raise RuntimeError("HF2 read failed for: " + ", ".join(missing))
        return {key: sample[key] for key in channels}
