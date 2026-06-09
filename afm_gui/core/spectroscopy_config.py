from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class SpectroscopyConfig:
    axis_name: str = "bias"
    axis_label: str = "Bias"
    axis_unit: str = "V"
    start: float = -1.0
    stop: float = 1.0
    points: int = 201
    dwell: float = 0.001
    settle: float = 0.02
    channels: tuple[str, ...] = ("current", "didv")
    scan_passes: tuple[str, ...] = ("trace",)

    def axis(self) -> np.ndarray:
        return np.linspace(self.start, self.stop, max(2, int(self.points)), dtype=float)


__all__ = ["SpectroscopyConfig"]
