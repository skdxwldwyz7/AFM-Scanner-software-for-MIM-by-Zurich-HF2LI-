import math

import numpy as np

from afm_gui.core.scan_config import ScanConfig, ScanDirection


def generate_scan_lines(config: ScanConfig, direction: int) -> list[tuple[np.ndarray, np.ndarray]]:
    rad = math.radians(config.angle)
    rot = np.array(
        [[math.cos(rad), -math.sin(rad)], [math.sin(rad), math.cos(rad)]],
        dtype=float,
    )
    center = np.array([config.xc, config.yc], dtype=float)

    if config.lines <= 1:
        offsets = np.array([0.0])
    else:
        offsets = np.linspace(-config.height / 2.0, config.height / 2.0, config.lines)

    if direction == ScanDirection.DOWN:
        offsets = offsets[::-1]

    lines = []
    for y_offset in offsets:
        start_local = np.array([-config.width / 2.0, y_offset], dtype=float)
        end_local = np.array([config.width / 2.0, y_offset], dtype=float)
        lines.append((rot @ start_local + center, rot @ end_local + center))
    return lines


def pos_to_voltage(point: np.ndarray, config: ScanConfig) -> tuple[float, float]:
    return point[0] * config.volts_per_nm_x, point[1] * config.volts_per_nm_y


def line_time(config: ScanConfig) -> float:
    move_time = config.width / max(config.linear, 1e-9)
    return move_time + config.pixels * config.t_sample + config.t_settle + config.t_rest
