"""Interruptible, speed-limited AUX XY ramps shared by scans and manual moves."""
from __future__ import annotations

import math


def ramp_xy(adapter, start, target, speed, stop, pause=lambda: None):
    adapter.validate_xy(*target)
    adapter.validate_xy(*start)
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("XY speed must be positive and finite")
    distance = math.hypot(target[0] - start[0], target[1] - start[1])
    if distance == 0:
        return tuple(start)
    steps = max(1, math.ceil(distance / adapter.xy_step_v))
    delay = distance / speed / steps
    current = tuple(start)
    for index in range(1, steps + 1):
        pause()
        if stop.is_set():
            break
        point = tuple(start[j] + (target[j] - start[j]) * index / steps for j in (0, 1))
        # Wait before each step: even a short move respects the requested speed.
        if stop.wait(delay):
            break
        pause()
        if stop.is_set():
            break
        adapter.set_xy_voltage(*point)
        current = point
    return current
