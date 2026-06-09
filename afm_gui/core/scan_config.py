from dataclasses import dataclass


DEFAULT_CHANNELS = ("topography", "error", "amplitude", "phase")
DEFAULT_SCAN_MODE = "topo"
SCAN_PASSES = ("trace", "retrace")


@dataclass(slots=True)
class ScanConfig:
    xc: float = 0.0
    yc: float = 0.0
    width: float = 500.0
    height: float = 500.0
    angle: float = 0.0
    pixels: int = 256
    lines: int = 256
    linear: float = 500.0
    t_sample: float = 0.001
    t_settle: float = 0.02
    t_rest: float = 0.01
    scan_mode: str = DEFAULT_SCAN_MODE
    channels: tuple[str, ...] = DEFAULT_CHANNELS
    scan_passes: tuple[str, ...] = SCAN_PASSES
    xy_unit: str = "nm"
    volts_per_nm_x: float = 1.0 / 1800.0
    volts_per_nm_y: float = 1.0 / 1800.0


class ScanDirection:
    DOWN = 0
    UP = 1
