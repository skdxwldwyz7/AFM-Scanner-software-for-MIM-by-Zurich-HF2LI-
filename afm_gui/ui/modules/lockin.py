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
    CHANNEL_INDEX = {"ch1": 0, "ch2": 1}

    def __init__(
        self,
        log_callback: Callable[[str], None],
        device_manager: DeviceManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._log_callback = log_callback
        self._device_manager = device_manager
        self._route_changed_callback: Callable[[dict[str, str]], None] | None = None
        self._applied_scan_routing: dict[str, dict[str, str]] = {}
        self.controllers = {
            channel: LockInController(self)
            for channel in self.CHANNELS
        }
        self.active_channels = self.CHANNELS
        self.widget = build_lockin_panel(self)
        self._connect()
        self._sync_available_channels()
        self._refresh_scan_route_devices()
        self.apply_scan_routing(log=False)
        if self._device_manager is not None:
            self._device_manager.devices_changed.connect(self._sync_available_channels)
            self._device_manager.devices_changed.connect(self._refresh_scan_route_devices)

    @property
    def primary_controller(self) -> LockInController:
        return self.controllers["ch1"]

    def snapshot(self) -> dict[str, object]:
        return {
            "active_channels": list(self.active_channels),
            "scan_routing": self.scan_routing(),
            "channels": {
                channel: controller.snapshot()
                for channel, controller in self.controllers.items()
                if channel in self.active_channels
            }
        }

    def scan_routing(self) -> dict[str, dict[str, str]]:
        if self._applied_scan_routing:
            return {
                channel: dict(route)
                for channel, route in self._applied_scan_routing.items()
            }
        return self._draft_scan_routing()

    def _draft_scan_routing(self) -> dict[str, dict[str, str]]:
        routes = {}
        for channel, controls in self.lockin_scan_routes.items():
            device_name = controls["device"].currentText().strip()
            routes[channel] = {
                "slot": str(controls.get("label", channel)).strip(),
                "device": device_name,
                "lockin_channel": controls["lockin_channel"].currentText().strip(),
                "signal": controls["signal"].currentText().strip(),
            }
        return routes

    def scan_channel_aliases(self) -> dict[str, str]:
        return {
            channel: self._route_label(route)
            for channel, route in self.scan_routing().items()
        }

    def set_route_changed_callback(self, callback: Callable[[dict[str, str]], None]) -> None:
        self._route_changed_callback = callback
        callback(self.scan_channel_aliases())

    def scan_adapters(self) -> dict[str, object]:
        if self._device_manager is None:
            return {}
        adapters = {}
        for channel, route in self.scan_routing().items():
            device_name = route.get("device", "")
            handle = self._device_manager.handles.get(device_name)
            if handle is not None and handle.connected and handle.adapter is not None:
                adapters[channel] = handle.adapter
        return adapters

    def _connect(self) -> None:
        for channel, controls in self.lockin_channels.items():
            controller = self.controllers[channel]
            controls["apply"].clicked.connect(lambda _checked=False, key=channel: self.apply_settings(key))
            controls["read"].clicked.connect(lambda _checked=False, key=channel: self.read(key))
            controller.reading_changed.connect(lambda reading, key=channel: self._show_reading(key, reading))
            controller.log_message.connect(lambda text, key=channel: self._log_callback(f"Lock-in {key}: {text}"))
        for controls in self.lockin_scan_routes.values():
            controls["device"].currentTextChanged.connect(
                lambda _text, route_controls=controls: self._refresh_route_channel_combo(route_controls)
            )
        self.lockin_apply_routes.clicked.connect(lambda _checked=False: self.apply_scan_routing())

    def apply_settings(self, channel: str) -> None:
        if channel not in self.active_channels:
            self._log_callback(f"Lock-in {channel} is not available for the assigned device")
            return
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
                        output_index=self._output_index(channel, adapter),
                        amplitude_index=self._amplitude_index(channel, adapter),
                    )
                    self._log_callback(f"Lock-in {channel} output command sent through lockin adapter")
                if hasattr(adapter, "configure_demod"):
                    adapter.configure_demod(
                        demod_index=self._demod_index(channel, adapter),
                        input_index=self._input_index(channel, adapter),
                        oscillator_index=self._oscillator_index(channel, adapter),
                        frequency_hz=controller.settings.frequency_hz,
                        phase_deg=controller.settings.phase_deg,
                        time_constant_s=controller.settings.time_constant_s,
                        enable=True,
                    )
                    self._log_callback(f"Lock-in {channel} demod configured through lockin adapter")
            except Exception as exc:
                self._log_callback(f"Lock-in hardware apply failed: {exc}")
        self.read(channel)

    def read(self, channel: str) -> None:
        if channel not in self.active_channels:
            self._log_callback(f"Lock-in {channel} is not available for the assigned device")
            return
        adapter = self._lockin_adapter()
        if adapter is None or not hasattr(adapter, "read_demod"):
            reading = LockInReading()
            controller = self.controllers[channel]
            controller.reading = reading
            controller.reading_changed.emit(reading)
            return
        try:
            sample = adapter.read_demod(demod_index=self._demod_index(channel, adapter))
            reading = LockInReading(
                x_v=float(sample.get("x_v") or 0.0),
                y_v=float(sample.get("y_v") or 0.0),
                r_v=float(sample.get("r_v") or 0.0),
                theta_deg=float(sample.get("phase_deg") or 0.0),
                frequency_hz=float(sample.get("frequency_hz") or 0.0),
            )
            controller = self.controllers[channel]
            controller.reading = reading
            controller.reading_changed.emit(reading)
            self._log_callback(f"Lock-in {channel} demod read through lockin adapter")
        except Exception as exc:
            self._log_callback(f"Lock-in hardware read failed: {exc}")
            self._show_read_error(channel)

    def _lockin_adapter(self) -> object | None:
        if self._device_manager is None:
            return None
        return self._device_manager.adapter_for_function("lockin")

    def _sync_available_channels(self) -> None:
        channels = self._available_channels()
        self.active_channels = channels
        for channel, controls in self.lockin_channels.items():
            box = controls.get("box")
            if box is not None:
                box.setVisible(channel in channels)

    def _available_channels(self) -> tuple[str, ...]:
        adapter = self._lockin_adapter()
        adapter_channels = self._channels_from_object(adapter)
        if adapter_channels:
            return adapter_channels

        if self._device_manager is None:
            return self.CHANNELS
        try:
            handle = self._device_manager.handle_for_function("lockin")
        except KeyError:
            return self.CHANNELS
        if handle is None:
            return self.CHANNELS
        return self._channels_for_driver(handle.config.driver)

    def _channels_from_object(self, source: object | None) -> tuple[str, ...]:
        if source is None:
            return ()
        raw = getattr(source, "lockin_channels", ())
        if callable(raw):
            raw = raw()
        raw = raw or ()
        channels = tuple(str(channel) for channel in raw if str(channel) in self.CHANNELS)
        return channels

    def _channels_for_driver(self, driver: str) -> tuple[str, ...]:
        if driver.startswith("srs."):
            return ("ch1",)
        if driver == "zurich.hf2li":
            return self.CHANNELS
        return self.CHANNELS

    def _refresh_scan_route_devices(self) -> None:
        if self._device_manager is None:
            return
        device_names = self._lockin_device_names()
        default_signals = {
            "signal_a": "x",
            "signal_b": "y",
            "signal_c": "r",
            "signal_d": "theta",
        }
        default_device = self._default_scan_route_device(device_names)
        for channel, controls in self.lockin_scan_routes.items():
            previous = controls["device"].currentText().strip()
            signal = controls["signal"].currentText().strip() or default_signals.get(channel, "x")
            selected = previous if previous in device_names else default_device
            controls["device"].blockSignals(True)
            controls["device"].clear()
            controls["device"].addItems(device_names)
            if selected in device_names:
                controls["device"].setCurrentText(selected)
            controls["device"].blockSignals(False)
            self._refresh_route_channel_combo(controls)
            if signal:
                controls["signal"].setCurrentText(signal)
        if not self._applied_scan_routing:
            self.apply_scan_routing(log=False)

    def _lockin_device_names(self) -> list[str]:
        if self._device_manager is None:
            return []
        return [
            name
            for name, handle in self._device_manager.handles.items()
            if "lockin_demod" in handle.capabilities()
        ]

    def _default_scan_route_device(self, device_names: list[str]) -> str:
        if self._device_manager is not None:
            try:
                handle = self._device_manager.handle_for_function("lockin")
            except KeyError:
                handle = None
            if handle is not None and handle.config.name in device_names:
                return handle.config.name
        return device_names[0] if device_names else ""

    def _refresh_route_channel_combo(self, controls: dict[str, object]) -> None:
        combo = controls["lockin_channel"]
        device_name = controls["device"].currentText().strip()
        channels = self._channels_for_device_name(device_name)
        previous = combo.currentText().strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(channels)
        if previous in channels:
            combo.setCurrentText(previous)
        elif channels:
            combo.setCurrentText(channels[0])
        combo.blockSignals(False)

    def _channels_for_device_name(self, device_name: str) -> tuple[str, ...]:
        if self._device_manager is None:
            return ("ch1",)
        handle = self._device_manager.handles.get(device_name)
        if handle is None:
            return ("ch1",)
        channels = self._channels_from_object(handle.adapter)
        if channels:
            return channels
        return self._channels_for_driver(handle.config.driver)

    def apply_scan_routing(self, *, log: bool = True) -> None:
        self._applied_scan_routing = self._draft_scan_routing()
        if self._route_changed_callback is not None:
            self._route_changed_callback(self.scan_channel_aliases())
        if log:
            self._log_scan_routing()

    def _route_label(self, route: dict[str, str]) -> str:
        slot = route.get("slot", "")
        device = route.get("device", "")
        signal = route.get("signal", "")
        pieces = [part for part in (slot, device, signal) if part]
        return "-".join(pieces) if pieces else slot

    def _log_scan_routing(self) -> None:
        routes = ", ".join(
            f"{route.get('slot', channel)} -> {route.get('device', '')}:{route.get('lockin_channel', '')} {route.get('signal', '')}"
            for channel, route in self.scan_routing().items()
        )
        self._log_callback(f"Lock-in scan routing: {routes}")

    def _demod_index(self, channel: str, adapter: object | None = None) -> int:
        if adapter is not None:
            index_for_channel = getattr(adapter, "demod_index_for_channel", None)
            if callable(index_for_channel):
                return int(index_for_channel(channel))
        return self.CHANNEL_INDEX.get(channel, 0)

    def _output_index(self, channel: str, adapter: object | None = None) -> int:
        if adapter is not None:
            index_for_channel = getattr(adapter, "output_index_for_channel", None)
            if callable(index_for_channel):
                return int(index_for_channel(channel))
        return self.CHANNEL_INDEX.get(channel, 0)

    def _input_index(self, channel: str, adapter: object | None = None) -> int:
        if adapter is not None:
            index_for_channel = getattr(adapter, "input_index_for_channel", None)
            if callable(index_for_channel):
                return int(index_for_channel(channel))
        return self.CHANNEL_INDEX.get(channel, 0)

    def _oscillator_index(self, channel: str, adapter: object | None = None) -> int:
        if adapter is not None:
            index_for_channel = getattr(adapter, "oscillator_index_for_channel", None)
            if callable(index_for_channel):
                return int(index_for_channel(channel))
        return self.CHANNEL_INDEX.get(channel, 0)

    def _amplitude_index(self, channel: str, adapter: object | None = None) -> int:
        if adapter is not None:
            index_for_channel = getattr(adapter, "amplitude_index_for_channel", None)
            if callable(index_for_channel):
                return int(index_for_channel(channel))
        return 6 + self.CHANNEL_INDEX.get(channel, 0)

    def _show_reading(self, channel: str, reading: object) -> None:
        controls = self.lockin_channels[channel]
        controls["x_label"].setText(f"{reading.x_v:.6g} V")
        controls["y_label"].setText(f"{reading.y_v:.6g} V")
        controls["r_label"].setText(f"{reading.r_v:.6g} V")
        controls["theta_label"].setText(f"{reading.theta_deg:.3f} deg")
        controls["frequency_label"].setText(f"{reading.frequency_hz:.6g} Hz")

    def _show_read_error(self, channel: str) -> None:
        controls = self.lockin_channels[channel]
        controls["x_label"].setText("Error")
        controls["y_label"].setText("-")
        controls["r_label"].setText("-")
        controls["theta_label"].setText("-")
        controls["frequency_label"].setText("-")


__all__ = ["LockInModule"]
