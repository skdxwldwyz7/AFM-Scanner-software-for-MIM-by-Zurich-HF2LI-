from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from afm_gui.device.paths import add_first_existing_path

MULTIFIELD_DIR = add_first_existing_path(
    "afm_gui/device/vendor/multifield",
    "Hardwares/MultiField",
    "Hardwares/Multifield",
    "Multifield",
)


class MultiFieldScannerAdapter:
    capabilities = ("scanner_voltage",)
    axis_channels = {"x": "ch1", "y": "ch2", "z": "ch3"}

    def __init__(self, instrument: Any) -> None:
        self.instrument = instrument

    def set_axis_voltage(self, axis: str, value_v: float) -> None:
        channel = self.axis_channels[axis]
        getattr(self.instrument, f"{channel}_v")(float(value_v))

    def get_axis_voltage(self, axis: str) -> float:
        channel = self.axis_channels[axis]
        return float(getattr(self.instrument, f"{channel}_v")())

    def stop(self) -> None:
        self.instrument.stop_output()

    def clear(self) -> None:
        self.instrument.clear_output()

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
            "axes": dict(self.axis_channels),
            "port": getattr(self.instrument, "port", ""),
        }

    def close(self) -> None:
        self.instrument.close()


class NewtonLT06StageAdapter:
    capabilities = ("xyz_stage",)

    def __init__(self, instrument: Any) -> None:
        self.instrument = instrument

    def move_absolute(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> None:
        if x is not None:
            self.instrument.x(float(x))
        if y is not None:
            self.instrument.y(float(y))
        if z is not None:
            self.instrument.z(float(z))

    def read_position(self) -> dict[str, float]:
        return {
            "x": float(self.instrument.x()),
            "y": float(self.instrument.y()),
            "z": float(self.instrument.z()),
        }

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
            "port": getattr(self.instrument, "port", ""),
        }

    def close(self) -> None:
        self.instrument.close()


def create_multifield_scanner(name: str, connection: dict[str, object]) -> tuple[object, MultiFieldScannerAdapter]:
    from MultiFieldScanner import MultiFieldScanner

    instrument = MultiFieldScanner(name, str(connection["port"]))
    return instrument, MultiFieldScannerAdapter(instrument)


def create_newton_lt06(name: str, connection: dict[str, object]) -> tuple[object, NewtonLT06StageAdapter]:
    from NewtonLT06 import NewtonLT06

    instrument = NewtonLT06(name, str(connection["port"]))
    return instrument, NewtonLT06StageAdapter(instrument)


__all__ = [
    "MultiFieldScannerAdapter",
    "NewtonLT06StageAdapter",
    "create_multifield_scanner",
    "create_newton_lt06",
]
