from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject

from afm_gui.core.approach_config import (
    ApproachConditionConfig,
    ApproachConfig,
    ApproachSafetyConfig,
    ApproachSignalConfig,
)
from afm_gui.core.approach_controller import ApproachController
from afm_gui.device.loader import DeviceManager
from afm_gui.ui.panels.approach import build_approach_panel


class ApproachModule(QObject):
    """Owns generic approach configuration, controls, and mock-safe execution."""

    SIGNAL_KEYS = {
        "x": "x_v",
        "y": "y_v",
        "r": "r_v",
        "theta": "phase_deg",
        "frequency": "frequency_hz",
    }

    def __init__(
        self,
        log_callback: Callable[[str], None],
        device_manager: DeviceManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._log_callback = log_callback
        self._device_manager = device_manager
        self.controller = ApproachController(self._actuator_provider, self._signal_provider, self)
        self.widget = build_approach_panel(self)
        self._connect()
        self._refresh_signal_devices()
        if self._device_manager is not None:
            self._device_manager.devices_changed.connect(self._refresh_signal_devices)
        self._update_button_state("Idle")

    def config(self) -> ApproachConfig:
        return ApproachConfig(
            actuator=self.approach_actuator.currentText().strip(),
            direction=self.approach_direction.currentText().strip(),
            step_um=self.approach_step.value(),
            settle_s=self.approach_settle.value(),
            signal=ApproachSignalConfig(
                device=self.approach_signal_device.currentText().strip(),
                channel=self.approach_signal_channel.currentText().strip(),
                quantity=self.approach_signal_quantity.currentText().strip(),
            ),
            condition=ApproachConditionConfig(
                condition_type=self.approach_condition_type.currentText().strip(),
                threshold=self.approach_threshold.value(),
                low=self.approach_low.value(),
                high=self.approach_high.value(),
                consecutive=self.approach_consecutive.value(),
            ),
            safety=ApproachSafetyConfig(
                max_travel_um=self.approach_max_travel.value(),
                max_steps=self.approach_max_steps.value(),
                retract_on_fail_um=self.approach_retract.value(),
            ),
        )

    def snapshot(self) -> dict[str, object]:
        return self.controller.snapshot()

    def start(self) -> None:
        self.controller.start(self.config())

    def read_signal_once(self) -> float:
        try:
            value = float(self._signal_provider()())
        except Exception as exc:
            self.approach_signal_value.setText("Error")
            self._log_callback(f"Approach signal read failed: {exc}")
            return 0.0
        self.approach_signal_value.setText(f"{value:.6g}")
        return value

    def _connect(self) -> None:
        self.approach_start.clicked.connect(self.start)
        self.approach_pause.clicked.connect(self.controller.pause)
        self.approach_resume.clicked.connect(self.controller.resume)
        self.approach_abort.clicked.connect(lambda _checked=False: self.controller.abort())
        self.approach_retract_button.clicked.connect(lambda: self.controller.retract(self.approach_retract.value()))
        self.approach_read_signal.clicked.connect(self.read_signal_once)
        self.controller.progress_changed.connect(self._show_progress)
        self.controller.state_changed.connect(self._update_button_state)
        self.controller.log_message.connect(lambda text: self._log_callback(f"Approach: {text}"))

    def _show_progress(self, progress: object) -> None:
        self.approach_state.setText(progress.state)
        self.approach_steps.setText(str(progress.steps))
        self.approach_travel.setText(f"{progress.travel_um:.6g} um")
        self.approach_signal_value.setText(f"{progress.signal_value:.6g}")
        self.approach_hits.setText(str(progress.consecutive_hits))

    def _update_button_state(self, state: str) -> None:
        running = state == "Approaching"
        paused = state == "Paused"
        self.approach_start.setEnabled(not running and not paused)
        self.approach_pause.setEnabled(running)
        self.approach_resume.setEnabled(paused)
        self.approach_abort.setEnabled(running or paused)
        self.approach_retract_button.setEnabled(not running)

    def _refresh_signal_devices(self) -> None:
        current = self.approach_signal_device.currentText().strip()
        devices = ["mock"]
        if self._device_manager is not None:
            devices.extend(
                name
                for name, handle in self._device_manager.handles.items()
                if "lockin_demod" in handle.capabilities()
            )
        self.approach_signal_device.blockSignals(True)
        self.approach_signal_device.clear()
        self.approach_signal_device.addItems(devices)
        if current in devices:
            self.approach_signal_device.setCurrentText(current)
        self.approach_signal_device.blockSignals(False)

    def _actuator_provider(self):
        config = self.config()
        if config.actuator == "mock.z":
            return self.controller._mock.move_relative
        if config.actuator == "coarse_stage.z" and self._device_manager is not None:
            adapter = self._device_manager.adapter_for_function("coarse_stage")
            if adapter is not None and hasattr(adapter, "move_relative"):
                return lambda dz_um: adapter.move_relative(dz=dz_um)
            if adapter is not None and hasattr(adapter, "read_position") and hasattr(adapter, "move_absolute"):
                def move_z(dz_um: float) -> None:
                    position = adapter.read_position()
                    adapter.move_absolute(z=float(position.get("z", 0.0)) + float(dz_um))

                return move_z
            raise RuntimeError("coarse_stage.z requires a connected coarse_stage adapter")
        raise RuntimeError(f"Unknown approach actuator: {config.actuator}")

    def _signal_provider(self):
        config = self.config()
        device_name = config.signal.device
        quantity = config.signal.quantity.lower()
        if not device_name or device_name == "mock":
            return self.controller._mock.signal
        if device_name and device_name != "mock" and self._device_manager is not None:
            handle = self._device_manager.handles.get(device_name)
            adapter = handle.adapter if handle is not None and handle.connected else None
            if adapter is not None and hasattr(adapter, "read_demod"):
                return lambda: self._read_lockin_signal(adapter, config.signal.channel, quantity)
            raise RuntimeError(f"{device_name} is not connected or does not provide lock-in readout")
        raise RuntimeError(f"Unknown approach signal device: {device_name}")

    def _read_lockin_signal(self, adapter: object, channel: str, quantity: str) -> float:
        demod_index = 0
        index_for_channel = getattr(adapter, "demod_index_for_channel", None)
        if callable(index_for_channel):
            demod_index = int(index_for_channel(channel))
        try:
            sample = adapter.read_demod(demod_index=demod_index)
        except TypeError:
            sample = adapter.read_demod()
        key = self.SIGNAL_KEYS.get(quantity, quantity)
        return float(sample.get(key) or 0.0)


__all__ = ["ApproachModule"]
