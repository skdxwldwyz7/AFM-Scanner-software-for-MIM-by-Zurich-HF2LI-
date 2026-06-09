from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PyQt6.QtCore import QObject

from afm_gui.core.stage_controller import StageController
from afm_gui.device.loader import DeviceManager
from afm_gui.ui.panels.stage_map import build_stage_map_panel


class StageModule(QObject):
    """Owns the stage panel, controller wiring, display updates, and metadata."""

    def __init__(
        self,
        log_callback: Callable[[str], None],
        device_manager: DeviceManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._log_callback = log_callback
        self._device_manager = device_manager
        self.controller = StageController(self)
        self.widget = build_stage_map_panel(self)
        self._connect()
        self._show_position(
            self.controller.position.x_um,
            self.controller.position.y_um,
            self.controller.position.z_um,
        )
        self._show_path(self.controller.path_array())

    def snapshot(self) -> dict[str, object]:
        return self.controller.snapshot()

    def _connect(self) -> None:
        self.stage_jog_up.clicked.connect(lambda: self._move_relative(0.0, self.stage_step.value()))
        self.stage_jog_down.clicked.connect(lambda: self._move_relative(0.0, -self.stage_step.value()))
        self.stage_jog_left.clicked.connect(lambda: self._move_relative(-self.stage_step.value(), 0.0))
        self.stage_jog_right.clicked.connect(lambda: self._move_relative(self.stage_step.value(), 0.0))
        self.stage_jog_z_up.clicked.connect(lambda: self._move_z_relative(self.stage_z_step.value()))
        self.stage_jog_z_down.clicked.connect(lambda: self._move_z_relative(-self.stage_z_step.value()))
        self.stage_move_absolute.clicked.connect(self._move_absolute)
        self.stage_move_z_absolute.clicked.connect(self._move_z_absolute)
        self.stage_home.clicked.connect(self._home)
        self.stage_home_z.clicked.connect(self._home_z)
        self.stage_clear_path.clicked.connect(self.controller.clear_path)
        self.controller.position_changed.connect(self._show_position)
        self.controller.path_changed.connect(self._show_path)
        self.controller.log_message.connect(self._log_callback)

    def _move_relative(self, dx_um: float, dy_um: float) -> None:
        self._move_stage(
            self.controller.position.x_um + dx_um,
            self.controller.position.y_um + dy_um,
            self.controller.position.z_um,
        )

    def _move_z_relative(self, dz_um: float) -> None:
        self._move_stage(
            self.controller.position.x_um,
            self.controller.position.y_um,
            self.controller.position.z_um + dz_um,
        )

    def _move_absolute(self) -> None:
        self._move_stage(self.stage_target_x.value(), self.stage_target_y.value(), self.controller.position.z_um)

    def _move_z_absolute(self) -> None:
        self._move_stage(self.controller.position.x_um, self.controller.position.y_um, self.stage_target_z.value())

    def _home(self) -> None:
        self._move_stage(0.0, 0.0, 0.0)

    def _home_z(self) -> None:
        self._move_stage(self.controller.position.x_um, self.controller.position.y_um, 0.0)

    def _move_stage(self, x_um: float, y_um: float, z_um: float) -> None:
        adapter = self._stage_adapter()
        if adapter is None:
            self.controller.move_absolute(x_um, y_um, z_um)
            return
        try:
            adapter.move_absolute(x=x_um, y=y_um, z=z_um)
            position = adapter.read_position()
            self.controller.move_absolute(
                float(position.get("x", x_um)),
                float(position.get("y", y_um)),
                float(position.get("z", z_um)),
            )
            self._log_callback("Stage command sent through coarse_stage adapter")
        except Exception as exc:
            self._log_callback(f"Stage hardware command failed: {exc}")

    def _stage_adapter(self) -> object | None:
        if self._device_manager is None:
            return None
        adapter = self._device_manager.adapter_for_function("coarse_stage")
        if adapter is None or not hasattr(adapter, "move_absolute"):
            return None
        return adapter

    def _show_position(self, x_um: float, y_um: float, z_um: float) -> None:
        self.stage_x_label.setText(f"{x_um:.3f} um")
        self.stage_y_label.setText(f"{y_um:.3f} um")
        self.stage_z_label.setText(f"{z_um:.3f} um")
        self.stage_target_x.setValue(x_um)
        self.stage_target_y.setValue(y_um)
        self.stage_target_z.setValue(z_um)
        self.stage_position_item.setData([x_um], [y_um])

    def _show_path(self, path: object) -> None:
        points = np.asarray(path, dtype=float)
        if points.size == 0:
            return
        self.stage_path_curve.setData(points[:, 0], points[:, 1])


__all__ = ["StageModule"]
