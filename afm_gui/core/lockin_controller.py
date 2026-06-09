from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(slots=True)
class LockInSettings:
    frequency_hz: float = 1000.0
    amplitude_v: float = 0.1
    phase_deg: float = 0.0
    time_constant_s: float = 0.1
    sensitivity_v: float = 1.0
    reserve: str = "Normal"
    output_enabled: bool = False


@dataclass(slots=True)
class LockInReading:
    x_v: float = 0.0
    y_v: float = 0.0
    r_v: float = 0.0
    theta_deg: float = 0.0


@dataclass(slots=True)
class PIDSettings:
    enabled: bool = False
    setpoint: float = 0.0
    p: float = 1.0
    i: float = 0.0
    d: float = 0.0
    output_min: float = -10.0
    output_max: float = 10.0


@dataclass(slots=True)
class PLLSettings:
    enabled: bool = False
    center_frequency_hz: float = 1000.0
    bandwidth_hz: float = 10.0
    phase_setpoint_deg: float = 0.0
    frequency_min_hz: float = 0.0
    frequency_max_hz: float = 10_000_000.0


class LockInController(QObject):
    settings_changed = pyqtSignal(object)
    pid_changed = pyqtSignal(object)
    pll_changed = pyqtSignal(object)
    reading_changed = pyqtSignal(object)
    log_message = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = LockInSettings()
        self.pid = PIDSettings()
        self.pll = PLLSettings()
        self.reading = LockInReading()
        self._rng = np.random.default_rng(123)

    def configure(
        self,
        *,
        frequency_hz: float | None = None,
        amplitude_v: float | None = None,
        phase_deg: float | None = None,
        time_constant_s: float | None = None,
        sensitivity_v: float | None = None,
        reserve: str | None = None,
        output_enabled: bool | None = None,
    ) -> None:
        self.settings = LockInSettings(
            frequency_hz=self.settings.frequency_hz if frequency_hz is None else float(frequency_hz),
            amplitude_v=self.settings.amplitude_v if amplitude_v is None else float(amplitude_v),
            phase_deg=self.settings.phase_deg if phase_deg is None else float(phase_deg),
            time_constant_s=self.settings.time_constant_s if time_constant_s is None else float(time_constant_s),
            sensitivity_v=self.settings.sensitivity_v if sensitivity_v is None else float(sensitivity_v),
            reserve=self.settings.reserve if reserve is None else str(reserve),
            output_enabled=self.settings.output_enabled if output_enabled is None else bool(output_enabled),
        )
        self.settings_changed.emit(self.settings)
        self.log_message.emit(
            "Lock-in configured: "
            f"f={self.settings.frequency_hz:.3f} Hz, "
            f"amp={self.settings.amplitude_v:.6g} V, "
            f"phase={self.settings.phase_deg:.3f} deg"
        )

    def configure_pid(
        self,
        *,
        enabled: bool | None = None,
        setpoint: float | None = None,
        p: float | None = None,
        i: float | None = None,
        d: float | None = None,
        output_min: float | None = None,
        output_max: float | None = None,
    ) -> None:
        self.pid = PIDSettings(
            enabled=self.pid.enabled if enabled is None else bool(enabled),
            setpoint=self.pid.setpoint if setpoint is None else float(setpoint),
            p=self.pid.p if p is None else float(p),
            i=self.pid.i if i is None else float(i),
            d=self.pid.d if d is None else float(d),
            output_min=self.pid.output_min if output_min is None else float(output_min),
            output_max=self.pid.output_max if output_max is None else float(output_max),
        )
        self.pid_changed.emit(self.pid)
        self.log_message.emit(
            "Lock-in PID configured: "
            f"enabled={self.pid.enabled}, setpoint={self.pid.setpoint:.6g}, "
            f"P={self.pid.p:.6g}, I={self.pid.i:.6g}, D={self.pid.d:.6g}"
        )

    def configure_pll(
        self,
        *,
        enabled: bool | None = None,
        center_frequency_hz: float | None = None,
        bandwidth_hz: float | None = None,
        phase_setpoint_deg: float | None = None,
        frequency_min_hz: float | None = None,
        frequency_max_hz: float | None = None,
    ) -> None:
        self.pll = PLLSettings(
            enabled=self.pll.enabled if enabled is None else bool(enabled),
            center_frequency_hz=self.pll.center_frequency_hz
            if center_frequency_hz is None
            else float(center_frequency_hz),
            bandwidth_hz=self.pll.bandwidth_hz if bandwidth_hz is None else float(bandwidth_hz),
            phase_setpoint_deg=self.pll.phase_setpoint_deg
            if phase_setpoint_deg is None
            else float(phase_setpoint_deg),
            frequency_min_hz=self.pll.frequency_min_hz if frequency_min_hz is None else float(frequency_min_hz),
            frequency_max_hz=self.pll.frequency_max_hz if frequency_max_hz is None else float(frequency_max_hz),
        )
        self.pll_changed.emit(self.pll)
        self.log_message.emit(
            "Lock-in PLL configured: "
            f"enabled={self.pll.enabled}, center={self.pll.center_frequency_hz:.3f} Hz, "
            f"bandwidth={self.pll.bandwidth_hz:.3f} Hz"
        )

    def read(self) -> LockInReading:
        amplitude = self.settings.amplitude_v if self.settings.output_enabled else 0.0
        phase_rad = math.radians(self.settings.phase_deg)
        noise_scale = max(self.settings.sensitivity_v, 1e-12) * 0.002
        x_v = amplitude * math.cos(phase_rad) + float(self._rng.normal(0.0, noise_scale))
        y_v = amplitude * math.sin(phase_rad) + float(self._rng.normal(0.0, noise_scale))
        r_v = math.hypot(x_v, y_v)
        theta_deg = math.degrees(math.atan2(y_v, x_v))
        self.reading = LockInReading(x_v=x_v, y_v=y_v, r_v=r_v, theta_deg=theta_deg)
        self.reading_changed.emit(self.reading)
        return self.reading

    def snapshot(self) -> dict[str, object]:
        return {
            "settings": {
                "frequency_hz": self.settings.frequency_hz,
                "amplitude_v": self.settings.amplitude_v,
                "phase_deg": self.settings.phase_deg,
                "time_constant_s": self.settings.time_constant_s,
                "sensitivity_v": self.settings.sensitivity_v,
                "reserve": self.settings.reserve,
                "output_enabled": self.settings.output_enabled,
            },
            "reading": {
                "x_v": self.reading.x_v,
                "y_v": self.reading.y_v,
                "r_v": self.reading.r_v,
                "theta_deg": self.reading.theta_deg,
            },
            "pid": {
                "enabled": self.pid.enabled,
                "setpoint": self.pid.setpoint,
                "p": self.pid.p,
                "i": self.pid.i,
                "d": self.pid.d,
                "output_min": self.pid.output_min,
                "output_max": self.pid.output_max,
            },
            "pll": {
                "enabled": self.pll.enabled,
                "center_frequency_hz": self.pll.center_frequency_hz,
                "bandwidth_hz": self.pll.bandwidth_hz,
                "phase_setpoint_deg": self.pll.phase_setpoint_deg,
                "frequency_min_hz": self.pll.frequency_min_hz,
                "frequency_max_hz": self.pll.frequency_max_hz,
            },
        }
