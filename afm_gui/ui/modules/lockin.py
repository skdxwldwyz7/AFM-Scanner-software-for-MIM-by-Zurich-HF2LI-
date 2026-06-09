from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject

from afm_gui.core.lockin_controller import LockInController
from afm_gui.core.lockin_controller import LockInReading
from afm_gui.device.loader import DeviceManager
from afm_gui.ui.panels.lockin import SENSITIVITIES, TIME_CONSTANTS, build_lockin_panel


class LockInModule(QObject):
    """Owns the two-channel lock-in panel, controllers, and metadata snapshot."""

    CHANNELS = ("ch1", "ch2")

    def __init__(
        self,
        log_callback: Callable[[str], None],
        device_manager: DeviceManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._log_callback = log_callback
        self._device_manager = device_manager
        self.controllers = {
            channel: LockInController(self)
            for channel in self.CHANNELS
        }
        self.widget = build_lockin_panel(self)
        self._connect()

    @property
    def primary_controller(self) -> LockInController:
        return self.controllers["ch1"]

    def snapshot(self) -> dict[str, object]:
        return {
            "channels": {
                channel: controller.snapshot()
                for channel, controller in self.controllers.items()
            }
        }

    def _connect(self) -> None:
        for channel, controls in self.lockin_channels.items():
            controller = self.controllers[channel]
            controls["apply"].clicked.connect(lambda _checked=False, key=channel: self.apply_settings(key))
            controls["read"].clicked.connect(lambda _checked=False, key=channel: self.read(key))
            controller.reading_changed.connect(lambda reading, key=channel: self._show_reading(key, reading))
            controller.log_message.connect(lambda text, key=channel: self._log_callback(f"Lock-in {key}: {text}"))

    def apply_settings(self, channel: str) -> None:
        controls = self.lockin_channels[channel]
        controller = self.controllers[channel]
        controller.configure(
            frequency_hz=controls["frequency"].value(),
            amplitude_v=controls["amplitude"].value(),
            phase_deg=controls["phase"].value(),
            time_constant_s=TIME_CONSTANTS[controls["time_constant"].currentIndex()],
            sensitivity_v=SENSITIVITIES[controls["sensitivity"].currentIndex()],
            reserve=controls["reserve"].currentText(),
            output_enabled=controls["output_enabled"].isChecked(),
        )
        adapter = self._lockin_adapter()
        if adapter is not None:
            try:
                if hasattr(adapter, "set_output"):
                    adapter.set_output(
                        amplitude=controller.settings.amplitude_v,
                        mixer_enable=controller.settings.output_enabled,
                        output_on=controller.settings.output_enabled,
                    )
                    self._log_callback("Lock-in output command sent through lockin adapter")
            except Exception as exc:
                self._log_callback(f"Lock-in hardware apply failed: {exc}")
        self.read(channel)

    def read(self, channel: str) -> None:
        adapter = self._lockin_adapter()
        if adapter is None or not hasattr(adapter, "read_demod"):
            self.controllers[channel].read()
            return
        try:
            sample = adapter.read_demod()
            reading = LockInReading(
                x_v=float(sample.get("x_v") or 0.0),
                y_v=float(sample.get("y_v") or 0.0),
                r_v=float(sample.get("r_v") or 0.0),
                theta_deg=float(sample.get("phase_deg") or 0.0),
            )
            controller = self.controllers[channel]
            controller.reading = reading
            controller.reading_changed.emit(reading)
            self._log_callback("Lock-in demod read through lockin adapter")
        except Exception as exc:
            self._log_callback(f"Lock-in hardware read failed: {exc}")
            self.controllers[channel].read()

    def _lockin_adapter(self) -> object | None:
        if self._device_manager is None:
            return None
        return self._device_manager.adapter_for_function("lockin")

    def _show_reading(self, channel: str, reading: object) -> None:
        controls = self.lockin_channels[channel]
        controls["x_label"].setText(f"{reading.x_v:.6g} V")
        controls["y_label"].setText(f"{reading.y_v:.6g} V")
        controls["r_label"].setText(f"{reading.r_v:.6g} V")
        controls["theta_label"].setText(f"{reading.theta_deg:.3f} deg")


__all__ = ["LockInModule"]
