from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from afm_gui.device.loader import DeviceManager
from afm_gui.device.registry import create_driver
from afm_gui.ui.panels.device_manager import (
    build_device_manager_panel,
    make_device_combo,
    make_editable_item,
    make_item,
)


class DeviceModule(QObject):
    """Owns the Device Manager panel, device loading, connections, and metadata."""

    def __init__(
        self,
        log_callback: Callable[[str], None],
        dialog_parent: QWidget,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._log_callback = log_callback
        self._dialog_parent = dialog_parent
        self._hardware_locked = False
        self._connection_busy = False
        self._connect_queue: list[str] = []
        self._connect_thread: QThread | None = None
        self._connect_worker: _DeviceConnectWorker | None = None
        self._connect_threads: list[QThread] = []
        self.manager = DeviceManager(self)
        self.widget = build_device_manager_panel(self)
        self._connect()
        self.refresh()

    def metadata_paths(self) -> dict[str, object]:
        return {
            "devices.config_path": str(self.manager.config_path),
            "devices.items": self.manager.snapshot(),
            "devices.functions": self.manager.function_snapshot(),
        }

    def set_hardware_locked(self, locked: bool) -> None:
        self._hardware_locked = bool(locked)
        self.manager.set_hardware_locked(locked)
        self._refresh_control_state()

    def wait_for_connections(self, timeout_ms: int = 5000) -> bool:
        deadline = timeout_ms
        for thread in list(self._connect_threads):
            if not thread.isRunning():
                continue
            if not thread.wait(max(0, deadline)):
                return False
            deadline = 0
        return True

    def _refresh_control_state(self) -> None:
        locked = self._hardware_locked or self._connection_busy
        for button in (
            self.load_devices,
            self.apply_device_connection,
            self.connect_device,
            self.disconnect_device,
            self.connect_enabled_devices,
            self.connect_assigned_devices,
            self.disconnect_all_devices,
        ):
            button.setEnabled(not locked)
        self.device_table.setEnabled(not locked)
        self.device_function_table.setEnabled(not locked)

    def refresh(self) -> None:
        self._refresh_device_table()

    def load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._dialog_parent,
            "Load Device Config",
            str(self.manager.config_path),
            "YAML Files (*.yaml *.yml)",
        )
        if path:
            try:
                self.manager.load_config(path)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self._dialog_parent, "Load Device Config", str(exc))

    def _connect(self) -> None:
        self.load_devices.clicked.connect(self.load_config)
        self.apply_device_connection.clicked.connect(self._apply_selected_device_connection)
        self.connect_device.clicked.connect(self._connect_selected_device)
        self.disconnect_device.clicked.connect(self._disconnect_selected_device)
        self.connect_enabled_devices.clicked.connect(self._connect_enabled_devices)
        self.connect_assigned_devices.clicked.connect(self._connect_assigned_devices)
        self.disconnect_all_devices.clicked.connect(self.manager.disconnect_all)
        self.manager.devices_changed.connect(self.refresh)
        self.manager.log_message.connect(self._log_callback)

    def _selected_device_name(self) -> str | None:
        row = self.device_table.currentRow()
        if row < 0:
            return None
        item = self.device_table.item(row, 0)
        return item.text() if item is not None else None

    def _connect_selected_device(self) -> None:
        name = self._selected_device_name()
        if not name:
            return
        self._connect_devices([name])

    def _connect_enabled_devices(self) -> None:
        names = [name for name, handle in self.manager.handles.items() if handle.config.enabled]
        self._connect_devices(names)

    def _connect_assigned_devices(self) -> None:
        names = []
        for function in self.manager.functions.values():
            if function.device and function.device not in names:
                names.append(function.device)
        self._connect_devices(names)

    def _connect_devices(self, names: list[str]) -> None:
        if self._hardware_locked:
            self._log_callback("Device connections are locked while a scan is active")
            return
        if self._connection_busy:
            self._log_callback("Device connection is already in progress")
            return
        self._connect_queue = [name for name in names if self._can_connect_device(name)]
        if not self._connect_queue:
            return
        self._connection_busy = True
        self._refresh_control_state()
        self._start_next_device_connection()

    def _can_connect_device(self, name: str) -> bool:
        handle = self.manager.handles.get(name)
        if handle is None:
            self._log_callback(f"Unknown device: {name}")
            return False
        if handle.connected:
            return False
        return True

    def _start_next_device_connection(self) -> None:
        if not self._connect_queue:
            self._connection_busy = False
            self._connect_thread = None
            self._connect_worker = None
            self._refresh_control_state()
            return
        name = self._connect_queue.pop(0)
        handle = self.manager.handles[name]
        handle.status = "Connecting"
        self.manager.device_status_changed.emit(name, handle.status)
        self.manager.devices_changed.emit()
        connection = dict(handle.config.connection)
        if handle.config.capabilities and "capabilities" not in connection:
            connection["capabilities"] = handle.config.capabilities
        self._log_callback(f"Connecting {name}...")
        thread = QThread(self)
        worker = _DeviceConnectWorker(
            name=name,
            driver=handle.config.driver,
            connection=connection,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._finish_device_connection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda finished_thread=thread: self._discard_connection_thread(finished_thread))
        thread.finished.connect(thread.deleteLater)
        self._connect_thread = thread
        self._connect_worker = worker
        self._connect_threads.append(thread)
        thread.start()

    def _discard_connection_thread(self, thread: QThread) -> None:
        if thread in self._connect_threads:
            self._connect_threads.remove(thread)

    def _finish_device_connection(
        self,
        name: str,
        status: str,
        message: str,
        instrument: object | None,
        adapter: object | None,
    ) -> None:
        handle = self.manager.handles.get(name)
        if handle is not None:
            handle.instrument = instrument
            handle.adapter = adapter
            handle.connected = status == "Connected"
            handle.status = status
            self.manager.device_status_changed.emit(name, handle.status)
            self.manager.devices_changed.emit()
        if message:
            self._log_callback(message)
        self._connect_thread = None
        self._connect_worker = None
        self._start_next_device_connection()

    def _disconnect_selected_device(self) -> None:
        name = self._selected_device_name()
        if not name:
            return
        self.manager.disconnect_device(name)

    def _apply_selected_device_connection(self) -> None:
        name = self._selected_device_name()
        if not name:
            return
        row = self.device_table.currentRow()
        connection_item = self.device_table.item(row, 4)
        enabled_item = self.device_table.item(row, 5)
        if connection_item is None:
            return
        try:
            connection = json.loads(connection_item.text())
            if not isinstance(connection, dict):
                raise ValueError("Connection must be a JSON object.")
            enabled = self._parse_enabled(enabled_item.text()) if enabled_item is not None else None
            self.manager.update_device_connection(name, connection)
            if enabled is not None:
                self.manager.update_device_enabled(name, enabled)
        except (json.JSONDecodeError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(self._dialog_parent, "Apply Connection", str(exc))

    def _refresh_device_table(self) -> None:
        snapshot = self.manager.snapshot()
        self.device_table.setRowCount(len(snapshot))
        for row, device in enumerate(snapshot):
            connection = json.dumps(device["connection"], sort_keys=True)
            values = (
                device["name"],
                device["kind"],
                ", ".join(device.get("capabilities", ())),
                device["driver"],
                connection,
                "yes" if device["enabled"] else "no",
                device["status"],
            )
            for column, value in enumerate(values):
                item = make_editable_item(value) if column in (4, 5) else make_item(value)
                self.device_table.setItem(row, column, item)
        if snapshot and self.device_table.currentRow() < 0:
            self.device_table.selectRow(0)
        self._refresh_device_function_table()

    def _refresh_device_function_table(self) -> None:
        functions = self.manager.function_snapshot()
        self.device_function_table.setRowCount(len(functions))
        for row, function in enumerate(functions):
            required_capability = str(function.get("required_capability", ""))
            required_kind = str(function["required_kind"])
            device_names = (
                self.manager.devices_for_capability(required_capability)
                if required_capability
                else self.manager.devices_for_kind(required_kind)
            )
            requirement = required_capability or required_kind
            self.device_function_table.setItem(row, 0, make_item(function["label"]))
            self.device_function_table.setItem(row, 1, make_item(requirement))
            combo = make_device_combo(device_names, str(function["device"]))
            combo.setEnabled(not self.manager.hardware_locked)
            combo.currentTextChanged.connect(
                lambda device_name, function_name=function["name"]: self._assign_device_function(
                    str(function_name),
                    device_name,
                )
            )
            self.device_function_table.setCellWidget(row, 2, combo)
            self.device_function_table.setItem(row, 3, make_item(function["device_status"]))

    def _assign_device_function(self, function_name: str, device_name: str) -> None:
        try:
            self.manager.assign_function(function_name, device_name)
        except (KeyError, ValueError) as exc:
            self._log_callback(str(exc))

    @staticmethod
    def _parse_enabled(text: str) -> bool:
        cleaned = text.strip().lower()
        if cleaned in {"yes", "true", "1", "on", "enabled"}:
            return True
        if cleaned in {"no", "false", "0", "off", "disabled"}:
            return False
        raise ValueError("Enabled must be yes/no or true/false.")


class _DeviceConnectWorker(QObject):
    finished = pyqtSignal(str, str, str, object, object)

    def __init__(self, *, name: str, driver: str, connection: dict[str, Any]) -> None:
        super().__init__()
        self._name = name
        self._driver = driver
        self._connection = dict(connection)

    @pyqtSlot()
    def run(self) -> None:
        try:
            instrument, adapter = create_driver(self._driver, self._name, self._connection)
        except NotImplementedError as exc:
            self.finished.emit(self._name, "Driver pending", str(exc), None, None)
        except Exception as exc:
            self.finished.emit(self._name, "Error", f"Could not connect {self._name}: {exc}", None, None)
        else:
            self.finished.emit(self._name, "Connected", f"Connected {self._name}", instrument, adapter)


__all__ = ["DeviceModule"]
