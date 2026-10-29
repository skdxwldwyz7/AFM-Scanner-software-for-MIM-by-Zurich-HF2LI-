"""Two external SR830 X channels, and a discrete low-pass settling advisor."""
from __future__ import annotations

import math
import re
import time

from afm_gui.core.fm_afm import FMAcquisition, FM_CHANNEL_BY_KEY


SR830_TIME_CONSTANTS = tuple(value * 10.0 ** exponent for exponent in range(-5, 5) for value in (1, 3))
MIM_ROUTES = {"sr830_I": "mim_i", "sr830_Q": "mim_q"}


def settling_factor(slope_db: int, fraction: float = 0.99) -> float:
    """Solve the step response of n identical RC poles, n = slope / 6."""
    if slope_db not in (6, 12, 18, 24) or not 0 < fraction < 1:
        raise ValueError("Use 6/12/18/24 dB/oct and a settling fraction between 0 and 1")
    order = slope_db // 6
    lower, upper = 0.0, 100.0
    for _ in range(70):
        mid = (lower + upper) / 2
        residual = math.exp(-mid) * sum(mid ** k / math.factorial(k) for k in range(order))
        if residual > 1 - fraction:
            lower = mid
        else:
            upper = mid
    return upper


def recommend_time_constant(line_s: float, pixels: int, slope_db: int = 24,
                            fraction: float = 0.99, *, dwell_s: float | None = None) -> dict:
    """Largest available tau within the settling budget; None means no valid setting.

    line_s is one active pass, excluding turnaround/line settle/rest. A stepped
    scan additionally limits the budget to the explicit wait at the pixel.
    """
    if not math.isfinite(line_s) or line_s <= 0 or pixels < 1:
        raise ValueError("Line time and pixel count must be positive")
    interval = line_s / pixels
    if dwell_s is not None and (not math.isfinite(dwell_s) or dwell_s < 0):
        raise ValueError("Pixel dwell must be finite and nonnegative")
    budget = min(interval, dwell_s) if dwell_s is not None else interval
    factor = settling_factor(slope_db, fraction)
    limit = budget / factor
    choices = [tau for tau in SR830_TIME_CONSTANTS if tau <= limit * (1 + 1e-12)]
    tau = choices[-1] if choices else None
    return {"line_s": line_s, "pixels": pixels, "pixel_interval_s": interval,
            "settling_budget_s": budget, "slope_db": slope_db, "fraction": fraction,
            "settling_factor": factor, "tau_limit_s": limit, "recommended_tau_s": tau,
            "settling_s": factor * tau if tau is not None else None}


def gpib_resource(address: str) -> tuple[int, int, int] | str:
    """Normalize VISA GPIB aliases (GPIB::8 and GPIB0::08::INSTR)."""
    text = address.strip().upper()
    match = re.fullmatch(r"GPIB(\d*)::(\d+)(?:::(\d+))?(?:::INSTR)?", text)
    if match:
        return int(match[1] or 0), int(match[2]), int(match[3] or 0)
    return text


class MIMAcquisition:
    """A pixel holds XY fixed until both sequential X queries have completed.

    No retries, display queries, software averaging, or per-pixel settings reads.
    Full returned precision is retained in float64 memory.
    """
    def __init__(self, hf2, i_adapter=None, q_adapter=None):
        self.hf2 = FMAcquisition(hf2)
        self.adapters = {key: adapter for key, adapter in
                         (("sr830_I", i_adapter), ("sr830_Q", q_adapter)) if adapter is not None}
        if i_adapter is not None and i_adapter is q_adapter:
            raise ValueError("MIM I and Q must use two distinct SR830 instruments")
        resources = []
        for key, adapter in self.adapters.items():
            if getattr(adapter, "model", "").upper() != "SR830" or not callable(getattr(adapter, "read_x", None)):
                raise ValueError(f"{key} requires an SR830 adapter")
            resource = gpib_resource(adapter.address)
            if not isinstance(resource, tuple):
                raise ValueError(f"{key} requires a GPIB VISA address")
            resources.append(resource)
        if len(resources) == 2 and resources[0] == resources[1]:
            raise ValueError("MIM I and Q have the same GPIB address")
        self.settings = {}
        self.count = 0
        self.total_read_s = self.max_read_s = 0.0
        self.pair_count = 0
        self.total_pair_gap_s = self.max_pair_gap_s = 0.0
        self.read_errors = {key: 0 for key in self.adapters}
        self.last_read_errors = {}
        self.settings_errors = {}
        self._log = lambda message: None

    def prepare(self, config, log):
        # All remote queries run in the scan thread, before any XY movement.
        self._log = log
        for key, adapter in self.adapters.items():
            try:
                self.settings[key] = adapter.read_mim_settings()
                self.validate_timing(config, log, keys=(key,))
            except Exception as exc:
                self.settings.pop(key, None)
                self.settings_errors[key] = str(exc)
                log(f"MIM {key}: settings unavailable ({exc}); continuing X acquisition")

    def validate_timing(self, config, log, keys=None):
        for key in keys or self.settings:
            setting = self.settings[key]
            settle_s = setting["time_constant_s"] * settling_factor(setting["slope_db"])
            detection_hz = setting["frequency_hz"] * setting["harmonic"]
            if setting["sync_filter"] and detection_hz < 203.12:
                settle_s += 1 / max(detection_hz, 1e-12)
            if config.t_sample < settle_s:
                log(f"MIM {key}: Sample={config.t_sample:g} s < estimated 99% settling "
                    f"{settle_s:.6g} s (tau={setting['time_constant_s']:g} s, "
                    f"{setting['slope_db']} dB/oct); spatial lag may occur")

    def __call__(self, channels):
        unknown = set(channels) - set(FM_CHANNEL_BY_KEY) - set(self.adapters)
        if unknown:
            raise ValueError("Unsupported MIM channels: " + ", ".join(sorted(unknown)))
        begin = time.perf_counter()
        sample, midpoints = {}, []
        for key, adapter in self.adapters.items():
            if key not in channels:
                continue
            start = time.perf_counter()
            try:
                value = float(adapter.read_x())
                if not math.isfinite(value):
                    raise ValueError("nonfinite X")
            except Exception as exc:
                value = math.nan
                self.read_errors[key] += 1
                self.last_read_errors[key] = str(exc)
                if self.read_errors[key] == 1:
                    self._log(f"MIM {key}: X read failed ({exc}); recording NaN and continuing scan")
            finish = time.perf_counter()
            sample[key] = value
            midpoints.append((start + finish) / 2)
        aux = tuple(key for key in channels if key in FM_CHANNEL_BY_KEY)
        if aux:
            sample.update(self.hf2(aux))
        duration = time.perf_counter() - begin
        self.count += 1
        self.total_read_s += duration
        self.max_read_s = max(self.max_read_s, duration)
        if len(midpoints) == 2:
            gap = abs(midpoints[1] - midpoints[0])
            self.pair_count += 1
            self.total_pair_gap_s += gap
            self.max_pair_gap_s = max(self.max_pair_gap_s, gap)
        return {key: sample[key] for key in channels}

    def snapshot(self):
        return {"routes": {key: adapter.address for key, adapter in self.adapters.items()},
                "settings_at_start": self.settings, "query": "OUTP? 1", "unit": "V",
                "pixel_reads": self.count,
                "read_error_counts": dict(self.read_errors),
                "last_read_errors": dict(self.last_read_errors),
                "settings_errors": dict(self.settings_errors),
                "sr830_status_checks": False,
                "mean_read_s": self.total_read_s / self.count if self.count else None,
                "max_read_s": self.max_read_s,
                "mean_pair_midpoint_gap_s": self.total_pair_gap_s / self.pair_count if self.pair_count else None,
                "max_pair_midpoint_gap_s": self.max_pair_gap_s,
                "timing_note": "Sequential host queries; midpoint gaps estimate communication skew, not instrument timestamps"}
