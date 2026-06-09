from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from PyQt6.QtCore import QObject, pyqtSignal

from afm_gui.device.registry import create_driver


@dataclass(slots=True)
class DeviceConfig:
    name: str
    label: str
    kind: str
    driver: str
    enabled: bool = True
    connection: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "DeviceConfig":
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("Device config is missing a name")
        return cls(
            name=name,
            label=str(raw.get("label") or name),
            kind=str(raw.get("kind") or "unknown"),
            driver=str(raw.get("driver") or "mock.generic"),
            enabled=bool(raw.get("enabled", True)),
            connection=dict(raw.get("connection") or {}),
            capabilities=tuple(str(item) for item in raw.get("capabilities", []) or ()),
        )


@dataclass(slots=True)
class DeviceFunction:
    name: str
    label: str
    required_kind: str = ""
    required_capability: str = ""
    device: str = ""

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "DeviceFunction":
        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValueError("Device function is missing a name")
        return cls(
            name=name,
            label=str(raw.get("label") or name),
            required_kind=str(raw.get("required_kind") or ""),
            required_capability=str(raw.get("required_capability") or ""),
            device=str(raw.get("device") or ""),
        )


@dataclass(slots=True)
class DeviceHandle:
    config: DeviceConfig
    connected: bool = False
    status: str = "Disconnected"
    instrument: object | None = None
    adapter: object | None = None

    def connect(self) -> None:
        if self.connected:
            return
        connection = dict(self.config.connection)
        if self.config.capabilities and "capabilities" not in connection:
            connection["capabilities"] = self.config.capabilities
        self.instrument, self.adapter = create_driver(self.config.driver, self.config.name, connection)
        self.connected = True
        self.status = "Connected"

    def disconnect(self) -> None:
        if self.adapter is not None and hasattr(self.adapter, "close"):
            self.adapter.close()
        elif self.instrument is not None and hasattr(self.instrument, "close"):
            self.instrument.close()
        self.adapter = None
        self.instrument = None
        self.connected = False
        self.status = "Disconnected"

    def capabilities(self) -> tuple[str, ...]:
        if self.adapter is not None:
            return tuple(getattr(self.adapter, "capabilities", ()))
        return self.config.capabilities

    def adapter_snapshot(self) -> dict[str, Any]:
        if self.adapter is not None and hasattr(self.adapter, "snapshot"):
            return dict(self.adapter.snapshot())
        return {}


def default_device_config_path() -> Path:
    return Path(str(resources.files("afm_gui.config").joinpath("devices.yaml")))


def load_device_config_file(path: str | Path | None = None) -> tuple[list[DeviceConfig], list[DeviceFunction]]:
    config_path = Path(path) if path is not None else default_device_config_path()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    devices = [DeviceConfig.from_mapping(item) for item in data.get("devices", [])]
    functions = [DeviceFunction.from_mapping(item) for item in data.get("functions", [])]
    return devices, functions


def load_device_configs(path: str | Path | None = None) -> list[DeviceConfig]:
    devices, _functions = load_device_config_file(path)
    return devices


class DeviceManager(QObject):
    devices_changed = pyqtSignal()
    device_status_changed = pyqtSignal(str, str)
    log_message = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config_path = default_device_config_path()
        self.handles: dict[str, DeviceHandle] = {}
        self.functions: dict[str, DeviceFunction] = {}
        self.hardware_locked = False
        self.load_config(self.config_path)

    def load_config(self, path: str | Path | None = None) -> None:
        if self.hardware_locked:
            self.log_message.emit("Device config is locked while a scan is active")
            return
        self.config_path = Path(path) if path is not None else default_device_config_path()
        configs, functions = load_device_config_file(self.config_path)
        self.handles = {config.name: DeviceHandle(config=config) for config in configs}
        self.functions = {function.name: function for function in functions}
        self.devices_changed.emit()
        self.log_message.emit(
            f"Loaded {len(self.handles)} device definitions and {len(self.functions)} functions from {self.config_path}"
        )

    def device_names(self) -> list[str]:
        return list(self.handles)

    def devices_for_kind(self, required_kind: str) -> list[str]:
        if not required_kind:
            return self.device_names()
        return [
            name
            for name, handle in self.handles.items()
            if handle.config.kind == required_kind
        ]

    def devices_for_capability(self, required_capability: str) -> list[str]:
        if not required_capability:
            return self.device_names()
        return [
            name
            for name, handle in self.handles.items()
            if required_capability in handle.capabilities()
        ]

    def assign_function(self, function_name: str, device_name: str) -> None:
        if self.hardware_locked:
            self.log_message.emit("Function assignments are locked while a scan is active")
            return
        if function_name not in self.functions:
            raise KeyError(f"Unknown device function: {function_name}")
        if device_name and device_name not in self.handles:
            raise KeyError(f"Unknown device: {device_name}")
        function = self.functions[function_name]
        if device_name:
            required = function.required_kind
            actual = self.handles[device_name].config.kind
            if required and actual != required:
                raise ValueError(f"Function {function_name} requires {required}, got {actual}")
            required_capability = function.required_capability
            if required_capability and required_capability not in self.handles[device_name].capabilities():
                raise ValueError(
                    f"Function {function_name} requires capability {required_capability}, got "
                    f"{', '.join(self.handles[device_name].capabilities()) or 'none'}"
                )
        function.device = device_name
        self.devices_changed.emit()

    def update_device_connection(self, name: str, connection: dict[str, Any]) -> None:
        if self.hardware_locked:
            raise RuntimeError("Device connections are locked while a scan is active")
        handle = self._handle(name)
        if handle.connected:
            raise RuntimeError(f"Disconnect {name} before changing its connection.")
        handle.config.connection = dict(connection)
        handle.status = "Configured"
        self.device_status_changed.emit(name, handle.status)
        self.devices_changed.emit()
        self.log_message.emit(f"Updated connection for {name}")

    def update_device_enabled(self, name: str, enabled: bool) -> None:
        if self.hardware_locked:
            self.log_message.emit("Device enabled states are locked while a scan is active")
            return
        handle = self._handle(name)
        handle.config.enabled = bool(enabled)
        self.devices_changed.emit()
        self.log_message.emit(f"{'Enabled' if enabled else 'Disabled'} {name}")

    def connect_device(self, name: str) -> None:
        if self.hardware_locked:
            self.log_message.emit("Device connections are locked while a scan is active")
            return
        handle = self._handle(name)
        try:
            handle.connect()
        except NotImplementedError as exc:
            handle.status = "Driver pending"
            self.log_message.emit(str(exc))
        except Exception as exc:
            handle.connected = False
            handle.status = "Error"
            self.log_message.emit(f"Could not connect {name}: {exc}")
        self.device_status_changed.emit(name, handle.status)
        self.devices_changed.emit()

    def disconnect_device(self, name: str) -> None:
        if self.hardware_locked:
            self.log_message.emit("Device disconnections are locked while a scan is active")
            return
        handle = self._handle(name)
        handle.disconnect()
        self.device_status_changed.emit(name, handle.status)
        self.devices_changed.emit()

    def connect_enabled(self) -> None:
        for name, handle in self.handles.items():
            if handle.config.enabled:
                self.connect_device(name)

    def connect_assigned(self) -> None:
        for function in self.functions.values():
            if function.device:
                self.connect_device(function.device)

    def disconnect_all(self) -> None:
        for name in list(self.handles):
            self.disconnect_device(name)

    def set_hardware_locked(self, locked: bool) -> None:
        self.hardware_locked = bool(locked)
        self.devices_changed.emit()

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": handle.config.name,
                "label": handle.config.label,
                "kind": handle.config.kind,
                "driver": handle.config.driver,
                "enabled": handle.config.enabled,
                "capabilities": handle.capabilities(),
                "connection": dict(handle.config.connection),
                "connected": handle.connected,
                "status": handle.status,
                "adapter": handle.adapter_snapshot(),
            }
            for handle in self.handles.values()
        ]

    def function_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "name": function.name,
                "label": function.label,
                "required_kind": function.required_kind,
                "required_capability": function.required_capability,
                "device": function.device,
                "device_status": self.handles[function.device].status if function.device in self.handles else "",
            }
            for function in self.functions.values()
        ]

    def handle_for_function(self, function_name: str) -> DeviceHandle | None:
        if function_name not in self.functions:
            raise KeyError(f"Unknown device function: {function_name}")
        device_name = self.functions[function_name].device
        if not device_name:
            return None
        return self.handles.get(device_name)

    def adapter_for_function(self, function_name: str) -> object | None:
        handle = self.handle_for_function(function_name)
        if handle is None or not handle.connected:
            return None
        return handle.adapter

    def _handle(self, name: str) -> DeviceHandle:
        if name not in self.handles:
            raise KeyError(f"Unknown device: {name}")
        return self.handles[name]
