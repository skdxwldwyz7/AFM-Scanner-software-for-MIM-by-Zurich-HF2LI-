from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass(slots=True)
class StagePosition:
    x_um: float = 0.0
    y_um: float = 0.0
    z_um: float = 0.0


class StageController(QObject):
    position_changed = pyqtSignal(float, float, float)
    path_changed = pyqtSignal(object)
    log_message = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.position = StagePosition()
        self._path: list[StagePosition] = [StagePosition()]

    def move_relative(self, dx_um: float, dy_um: float, dz_um: float = 0.0) -> None:
        self.move_absolute(
            self.position.x_um + dx_um,
            self.position.y_um + dy_um,
            self.position.z_um + dz_um,
        )

    def move_absolute(self, x_um: float, y_um: float, z_um: float | None = None) -> None:
        z_value = self.position.z_um if z_um is None else float(z_um)
        self.position = StagePosition(float(x_um), float(y_um), z_value)
        self._path.append(StagePosition(self.position.x_um, self.position.y_um, self.position.z_um))
        self.position_changed.emit(self.position.x_um, self.position.y_um, self.position.z_um)
        self.path_changed.emit(self.path_array())
        self.log_message.emit(
            "Stage moved to "
            f"x={self.position.x_um:.3f} um, y={self.position.y_um:.3f} um, z={self.position.z_um:.3f} um"
        )

    def home(self) -> None:
        self.move_absolute(0.0, 0.0, 0.0)

    def move_z_relative(self, dz_um: float) -> None:
        self.move_relative(0.0, 0.0, dz_um)

    def move_z_absolute(self, z_um: float) -> None:
        self.move_absolute(self.position.x_um, self.position.y_um, z_um)

    def home_z(self) -> None:
        self.move_z_absolute(0.0)

    def clear_path(self) -> None:
        self._path = [StagePosition(self.position.x_um, self.position.y_um, self.position.z_um)]
        self.path_changed.emit(self.path_array())

    def path_array(self) -> np.ndarray:
        return np.array([[point.x_um, point.y_um, point.z_um] for point in self._path], dtype=float)

    def snapshot(self) -> dict[str, object]:
        return {
            "position_um": {
                "x": self.position.x_um,
                "y": self.position.y_um,
                "z": self.position.z_um,
            },
            "path_points": len(self._path),
        }
