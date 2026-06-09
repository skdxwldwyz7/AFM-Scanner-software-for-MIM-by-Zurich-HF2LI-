from __future__ import annotations

from collections.abc import Callable
import threading
import time

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from afm_gui.core.scan_config import ScanConfig
from afm_gui.core.scan_geometry import pos_to_voltage
from afm_gui.device.mock_device import MockScannerDevice


AcquisitionCallback = Callable[[tuple[str, ...]], dict[str, float]]
AcquisitionCallbackProvider = Callable[[], AcquisitionCallback | None]
ScannerAdapterProvider = Callable[[], object | None]


class AdapterScannerDevice(QObject):
    """Scanner-device bridge that keeps hardware I/O out of the GUI thread."""

    line_data_ready = pyqtSignal(int, object)
    scan_progress_changed = pyqtSignal(int, int, int, int, str)
    command_logged = pyqtSignal(str)
    scan_finished = pyqtSignal()

    def __init__(
        self,
        scanner_adapter_provider: ScannerAdapterProvider,
        acquisition_callback_provider: AcquisitionCallbackProvider | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scanner_adapter_provider = scanner_adapter_provider
        self._acquisition_callback_provider = acquisition_callback_provider
        self._mock = MockScannerDevice(self)
        self._mock.line_data_ready.connect(lambda line_index, data: self.line_data_ready.emit(line_index, data))
        self._mock.command_logged.connect(self.command_logged.emit)
        self._mock.scan_finished.connect(self.scan_finished.emit)
        self._config = ScanConfig()
        self._lines: list[tuple[np.ndarray, np.ndarray]] = []
        self._using_mock = False
        self._thread: QThread | None = None
        self._worker: _AdapterScanWorker | None = None

    def configure_scan(self, config: ScanConfig, lines: list[tuple[np.ndarray, np.ndarray]]) -> None:
        self._config = config
        self._lines = lines

    def send_commands(self, commands: list[str]) -> None:
        for command in commands:
            self.command_logged.emit(command.rstrip())

    def start_scan(
        self,
        line_count: int,
        pixels: int,
        interval_ms: int,
        channels: tuple[str, ...],
    ) -> None:
        adapter = self._scanner_adapter_provider()
        if adapter is None or not hasattr(adapter, "set_axis_voltage"):
            self._using_mock = True
            self.command_logged.emit("No connected scan_scanner adapter; using mock scanner fallback")
            self._mock.start_scan(line_count, pixels, interval_ms, channels)
            return

        self._using_mock = False
        self._start_worker(adapter, channels)

    def pause(self) -> None:
        if self._using_mock:
            self._mock.pause()
            return
        if self._worker is not None:
            self._worker.request_pause()

    def resume(self, interval_ms: int) -> None:
        if self._using_mock:
            self._mock.resume(interval_ms)
            return
        if self._worker is not None:
            self._worker.request_resume()

    def set_line_interval(self, interval_ms: int) -> None:
        if self._using_mock:
            self._mock.set_line_interval(interval_ms)

    def stop(self) -> None:
        if self._using_mock:
            self._mock.stop()
            return
        if self._worker is not None:
            self._worker.request_stop()
            return
        self.scan_finished.emit()

    def _start_worker(self, adapter: object, channels: tuple[str, ...]) -> None:
        if self._worker is not None:
            self._worker.request_stop()
        thread = QThread(self)
        acquisition_callback = self._acquisition_callback_provider() if self._acquisition_callback_provider else None
        worker = _AdapterScanWorker(
            adapter=adapter,
            config=self._config,
            lines=self._lines,
            channels=channels,
            acquisition_callback=acquisition_callback,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.line_data_ready.connect(lambda line_index, data: self.line_data_ready.emit(line_index, data))
        worker.scan_progress_changed.connect(self.scan_progress_changed.emit)
        worker.command_logged.connect(self.command_logged.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self.command_logged.emit("Using scan_scanner adapter in background worker")
        thread.start()

    def _on_worker_finished(self) -> None:
        self._worker = None
        self._thread = None
        self.scan_finished.emit()

    def wait_for_finished(self, timeout_ms: int = 5000) -> bool:
        thread = self._thread
        if thread is None:
            return True
        if self._worker is not None:
            self._worker.request_stop()
        return bool(thread.wait(timeout_ms))


class _AdapterScanWorker(QObject):
    line_data_ready = pyqtSignal(int, object)
    scan_progress_changed = pyqtSignal(int, int, int, int, str)
    command_logged = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        *,
        adapter: object,
        config: ScanConfig,
        lines: list[tuple[np.ndarray, np.ndarray]],
        channels: tuple[str, ...],
        acquisition_callback: AcquisitionCallback | None,
    ) -> None:
        super().__init__()
        self._adapter = adapter
        self._config = config
        self._lines = list(lines)
        self._channels = channels
        self._acquisition_callback = acquisition_callback
        self._stop_requested = threading.Event()
        self._pause_requested = threading.Event()
        self._missing_sample_logged = False

    @pyqtSlot()
    def run(self) -> None:
        try:
            for line_index, (start, end) in enumerate(self._lines):
                if self._stop_requested.is_set():
                    break
                self._wait_if_paused()
                if self._stop_requested.is_set():
                    break
                data = self._acquire_line(line_index, start, end)
                self.line_data_ready.emit(line_index, data)
                if self._config.t_rest > 0:
                    self._sleep(self._config.t_rest)
        except Exception as exc:
            self.command_logged.emit(f"Scan adapter acquisition failed: {exc}")
        finally:
            self._stop_adapter()
            self.finished.emit()

    def request_stop(self) -> None:
        self._stop_requested.set()
        self._pause_requested.clear()

    def request_pause(self) -> None:
        self._pause_requested.set()

    def request_resume(self) -> None:
        self._pause_requested.clear()

    def _acquire_line(self, line_index: int, start: np.ndarray, end: np.ndarray) -> dict[str, dict[str, np.ndarray]]:
        trace = self._acquire_pass(line_index, "trace", start, end)
        data: dict[str, dict[str, np.ndarray]] = {
            channel: {"trace": trace[channel]}
            for channel in self._channels
        }
        if "retrace" in self._config.scan_passes:
            retrace = self._acquire_pass(line_index, "retrace", end, start)
            for channel in self._channels:
                data[channel]["retrace"] = retrace[channel]
        return data

    def _acquire_pass(self, line_index: int, scan_pass: str, start: np.ndarray, end: np.ndarray) -> dict[str, np.ndarray]:
        pixels = max(1, int(self._config.pixels))
        values = {
            channel: np.zeros(pixels, dtype=float)
            for channel in self._channels
        }
        points = np.linspace(start, end, pixels)
        progress_step = max(1, pixels // 100)
        last_progress_emit = 0.0
        if len(points):
            self._set_xy_voltage(points[0])
            self._sleep(self._config.t_settle)
        for index, point in enumerate(points):
            self._wait_if_paused()
            if self._stop_requested.is_set():
                break
            if index:
                self._set_xy_voltage(point)
            sample = self._read_sample()
            if not sample and not self._missing_sample_logged:
                self.command_logged.emit("Acquisition callback returned no channel data; filling samples with 0")
                self._missing_sample_logged = True
            for channel in self._channels:
                if channel in sample:
                    values[channel][index] = float(sample[channel])
            now = time.monotonic()
            should_emit_progress = (
                index == 0
                or index == pixels - 1
                or index % progress_step == 0
                or now - last_progress_emit >= 0.1
            )
            if should_emit_progress:
                self.scan_progress_changed.emit(line_index, self._config.lines, index, pixels, scan_pass)
                last_progress_emit = now
            self._sleep(self._config.t_sample)
        return values

    def _set_xy_voltage(self, point: np.ndarray) -> None:
        x_v, y_v = pos_to_voltage(point, self._config)
        self._adapter.set_axis_voltage("x", x_v)
        self._adapter.set_axis_voltage("y", y_v)

    def _read_sample(self) -> dict[str, float]:
        if self._acquisition_callback is None:
            return {}
        return self._acquisition_callback(self._channels)

    def _wait_if_paused(self) -> None:
        while self._pause_requested.is_set() and not self._stop_requested.is_set():
            time.sleep(0.01)

    def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        deadline = time.monotonic() + seconds
        while not self._stop_requested.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.01))

    def _stop_adapter(self) -> None:
        if hasattr(self._adapter, "stop"):
            try:
                self._adapter.stop()
            except Exception as exc:
                self.command_logged.emit(f"Could not stop scan_scanner adapter: {exc}")


__all__ = ["AdapterScannerDevice", "AcquisitionCallback", "AcquisitionCallbackProvider", "ScannerAdapterProvider"]
