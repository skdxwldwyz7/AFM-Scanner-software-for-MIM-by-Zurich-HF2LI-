from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from afm_gui.device.paths import add_first_existing_path

ATTOCUBE_PYTHON_DIR = add_first_existing_path(
    "afm_gui/device/vendor/attocube/python",
    "Hardwares/Attocube/python",
    "Attocube/python",
)


class AttocubeAMCStageAdapter:
    """GUI-compatible adapter for attocube AMC closed-loop XYZ stages."""

    capabilities = ("xyz_stage",)

    def __init__(
        self,
        instrument: Any,
        connection: dict[str, object],
        *,
        axis_map: dict[str, int] | None = None,
    ) -> None:
        self.instrument = instrument
        self.connection = dict(connection)
        self.axis_map = axis_map or {"x": 0, "y": 1, "z": 2}

    def move_absolute(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
    ) -> None:
        for axis_name, value_um in (("x", x), ("y", y), ("z", z)):
            if value_um is None:
                continue
            axis = self._axis(axis_name)
            self.instrument.control.setControlOutput(axis, True)
            self.instrument.move.setControlTargetPosition(axis, self._um_to_nm(value_um))
            self.instrument.control.setControlMove(axis, True)

    def move_relative(
        self,
        dx: float = 0.0,
        dy: float = 0.0,
        dz: float = 0.0,
    ) -> None:
        current = self.read_position()
        self.move_absolute(
            current["x"] + float(dx),
            current["y"] + float(dy),
            current["z"] + float(dz),
        )

    def read_position(self) -> dict[str, float]:
        return {
            axis_name: self._nm_to_um(self.instrument.move.getPosition(axis))
            for axis_name, axis in self.axis_map.items()
        }

    def status(self) -> dict[str, object]:
        axes: dict[str, dict[str, object]] = {}
        for axis_name, axis in self.axis_map.items():
            axes[axis_name] = {
                "axis": axis,
                "position_um": self._nm_to_um(self.instrument.move.getPosition(axis)),
                "connected": self.instrument.status.getStatusConnected(axis),
                "moving": self.instrument.status.getStatusMoving(axis),
                "target_range": self.instrument.status.getStatusTargetRange(axis),
                "output": self.instrument.control.getControlOutput(axis),
            }
        return {"axes": axes}

    def set_output(self, axis_name: str, enabled: bool) -> None:
        self.instrument.control.setControlOutput(self._axis(axis_name), bool(enabled))

    def step(self, axis_name: str, *, backward: bool = False, count: int = 1) -> None:
        axis = self._axis(axis_name)
        self.instrument.control.setControlOutput(axis, True)
        if count == 1:
            self.instrument.move.setSingleStep(axis, bool(backward))
        else:
            self.instrument.move.setNSteps(axis, bool(backward), int(count))

    def stop(self, axis_name: str | None = None) -> None:
        axis_names = (axis_name,) if axis_name is not None else tuple(self.axis_map)
        for name in axis_names:
            axis = self._axis(name)
            self.instrument.control.setControlMove(axis, False)
            self.instrument.move.setControlContinuousFwd(axis, False)
            self.instrument.move.setControlContinuousBkwd(axis, False)

    def search_reference(self, axis_name: str) -> None:
        axis = self._axis(axis_name)
        self.instrument.control.setControlOutput(axis, True)
        self.instrument.control.searchReferencePosition(axis)

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
            "host": self.connection.get("host", "192.168.1.1"),
            "port": self.connection.get("port", 9090),
            "axes": dict(self.axis_map),
        }

    def close(self) -> None:
        if bool(self.connection.get("stop_on_close", False)):
            self.stop()
        self.instrument.close()

    def _axis(self, axis_name: str) -> int:
        normalized = axis_name.lower()
        if normalized not in self.axis_map:
            raise KeyError(f"Unknown attocube axis: {axis_name}")
        return self.axis_map[normalized]

    @staticmethod
    def _um_to_nm(value_um: float) -> int:
        return int(round(float(value_um) * 1000.0))

    @staticmethod
    def _nm_to_um(value_nm: float) -> float:
        return float(value_nm) / 1000.0


def _axis_map_from_connection(connection: dict[str, object]) -> dict[str, int]:
    raw_axes = connection.get("axes")
    if not isinstance(raw_axes, dict):
        return {"x": 0, "y": 1, "z": 2}
    axis_map = {"x": 0, "y": 1, "z": 2}
    for axis_name in axis_map:
        if axis_name in raw_axes:
            axis_map[axis_name] = int(raw_axes[axis_name])
    return axis_map


def create_attocube_anc350(name: str, connection: dict[str, object]) -> tuple[object, AttocubeAMCStageAdapter]:
    import AMC

    host = str(connection.get("host", "192.168.1.1"))
    instrument = AMC.Device(host)
    if "port" in connection:
        instrument.TCP_PORT = int(connection["port"])
    instrument.connect()
    adapter = AttocubeAMCStageAdapter(instrument, connection, axis_map=_axis_map_from_connection(connection))
    if bool(connection.get("output_on_connect", False)):
        for axis in adapter.axis_map.values():
            instrument.control.setControlOutput(axis, True)
    return instrument, adapter


__all__ = ["AttocubeAMCStageAdapter", "create_attocube_anc350"]
