"""FM-AFM channel definitions shared by acquisition, plots and exports.

HF2 node reference: https://docs.zhinst.com/hf2_user_manual/nodedoc.html
All voltages are HF2 low-voltage signals, NOT scanner high voltage or height.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FMChannel:
    key: str
    label: str
    unit: str


FM_CHANNELS = (
    FMChannel("frequency", "Tracked frequency", "Hz"),
    FMChannel("pll_df", "PLL frequency shift", "Hz"),
    FMChannel("pll_error", "PLL phase error", "deg"),
    FMChannel("pll_locked", "PLL locked", "bool"),
    FMChannel("pll_enabled", "PLL enabled", "bool"),
    FMChannel("pll_center", "PLL center frequency", "Hz"),
    FMChannel("pll_range", "PLL frequency range", "Hz"),
    FMChannel("pll_setpoint", "PLL phase setpoint", "deg"),
    FMChannel("x", "Demod X", "V"),
    FMChannel("y", "Demod Y", "V"),
    FMChannel("r", "Demod amplitude R", "V"),
    FMChannel("theta", "Demod phase", "deg"),
    FMChannel("auxin1", "Aux In 1 / df voltage", "V"),
    FMChannel("auxin2", "Aux In 2", "V"),
    FMChannel("pid_error", "Z PID error", "V"),
    FMChannel("pid_shift", "Z PID shift", "V"),
    FMChannel("pid_out", "Z PID center + shift (derived)", "V"),
    FMChannel("pid_enabled", "Z PID enabled", "bool"),
    FMChannel("pid_setpoint", "Z PID setpoint", "V"),
    FMChannel("pid_center", "Z PID center", "V"),
    FMChannel("pid_range", "Z PID range", "V"),
    FMChannel("pid_at_limit", "Z PID at limit (derived)", "bool"),
    FMChannel("auxout1", "Aux Out 1 / X", "V"),
    FMChannel("auxout2", "Aux Out 2 / Y", "V"),
    FMChannel("auxout3", "Aux Out 3 / Z PID output", "V"),
    FMChannel("auxout4", "Aux Out 4 / PLL Δf output", "V"),
    FMChannel("aux4_scale", "Aux 4 scale", "V/Hz"),
    FMChannel("aux4_offset", "Aux 4 offset", "V"),
    FMChannel("loopback_error", "Aux In 1 - Aux Out 4 (derived)", "V"),
)
FM_CHANNEL_BY_KEY = {item.key: item for item in FM_CHANNELS}


class FMAcquisition:
    """Keep missing measurements missing; never synthesize FM-AFM readings."""

    def __init__(self, adapter: object) -> None:
        self.adapter = adapter

    def __call__(self, channels: tuple[str, ...]) -> dict[str, float]:
        sample = self.adapter.read_fm_snapshot(set(channels) | {"pll_locked", "pll_enabled", "pid_enabled", "auxout3"})
        if any(sample.get(key) != 1 for key in ("pll_locked", "pll_enabled", "pid_enabled")):
            raise RuntimeError("PLL unlocked/off or PID off: XY scan stopped; inspect LabOne")
        self.adapter.check_z_voltage(sample.get("auxout3", math.nan))
        missing = [key for key in channels if not math.isfinite(sample.get(key, math.nan))]
        if missing:
            raise RuntimeError("HF2 read failed for: " + ", ".join(missing))
        return {key: sample[key] for key in channels}
