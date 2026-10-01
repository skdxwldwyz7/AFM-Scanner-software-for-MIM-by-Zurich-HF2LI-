from __future__ import annotations

from collections import deque
import csv
from datetime import datetime, timezone
import math
import threading
import time

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog

from afm_gui.core.fm_afm import FM_CHANNELS, FM_CHANNEL_BY_KEY
from afm_gui.core.xy_motion import ramp_xy
from afm_gui.ui.panels.fm_afm import build_fm_afm_panel


class FMAFMModule(QObject):
    """Read-only telemetry and explicitly requested XY moves; bounded history."""
    activity_changed = pyqtSignal()
    HISTORY_LIMIT = 3600

    def __init__(self, device_manager, log_callback, parent=None):
        super().__init__(parent)
        self.manager = device_manager
        self._log = log_callback
        self.history = deque(maxlen=self.HISTORY_LIMIT)
        self.latest = {}
        self.last_timestamp = ""
        self._epoch = time.monotonic()
        self._monitor_thread = None
        self._monitor_worker = None
        self._move_thread = None
        self._move_worker = None
        self._scan_active = False
        self._external_motion = False
        self.widget = build_fm_afm_panel(self)
        self.monitor_start.clicked.connect(lambda: self.start_monitor())
        self.monitor_read.clicked.connect(lambda: self.start_monitor(once=True))
        self.monitor_stop.clicked.connect(self.stop_monitor)
        self.monitor_export.clicked.connect(self.export_history)
        self.monitor_clear.clicked.connect(self.clear_history)
        self.xy_move.clicked.connect(self.move_xy)
        self.xy_stop.clicked.connect(self.stop_xy)
        self.xy_read.clicked.connect(self.copy_live_xy)
        for selector, _plot, _curve in self.time_views:
            selector.currentIndexChanged.connect(self.refresh_plots)
        self.manager.devices_changed.connect(self.refresh_connection)
        self._update_controls()

    @property
    def busy(self):
        return self._monitor_thread is not None or self.moving

    @property
    def moving(self):
        return self._move_thread is not None

    def adapter(self):
        adapter = self.manager.adapter_for_function("lockin")
        if adapter is None or not hasattr(adapter, "read_fm_snapshot"):
            raise RuntimeError("Connect Zurich HF2LI in Device Manager first")
        return adapter

    def refresh_connection(self):
        try:
            adapter = self.adapter()
        except RuntimeError:
            if not self.busy:
                self.monitor_status.setText("Disconnected / displayed history is not live")
            return
        for control in (self.xy_x, self.xy_y):
            control.setRange(adapter.xy_min_v, adapter.xy_max_v)
        self.xy_limits.setText(
            f"AUX XY limits {adapter.xy_min_v:g}…{adapter.xy_max_v:g} V; "
            f"max step {adapter.xy_step_v:g} V. Stop holds voltage; Z stays in LabOne."
        )

    def set_scan_active(self, active):
        self._scan_active = active
        self._update_controls()

    def set_external_motion(self, active):
        self._external_motion = active
        self._update_controls()

    def start_monitor(self, *, once=False):
        if self._monitor_thread is not None:
            return
        try:
            adapter = self.adapter()
        except RuntimeError as exc:
            self._log(str(exc))
            return
        worker = _MonitorWorker(adapter, self.monitor_interval.value() / 1000, once)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.sample.connect(self._show_sample)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._monitor_finished)
        thread.finished.connect(thread.deleteLater)
        self._monitor_worker, self._monitor_thread = worker, thread
        self.monitor_status.setText("Reading HF2…")
        self._update_controls()
        self.activity_changed.emit()
        thread.start()

    def stop_monitor(self):
        if self._monitor_worker is not None:
            self._monitor_worker.stop.set()

    def _monitor_finished(self):
        self._monitor_thread = self._monitor_worker = None
        self.monitor_status.setText(f"Monitor stopped — last sample {self.last_timestamp or 'N/A'}")
        self._update_controls()
        self.activity_changed.emit()

    def _show_sample(self, timestamp, monotonic, values, errors):
        self.latest = dict(values)
        self.last_timestamp = timestamp
        self.history.append((timestamp, monotonic - self._epoch, dict(values)))
        for row, channel in enumerate(FM_CHANNELS):
            value = values.get(channel.key, math.nan)
            text = "N/A" if not math.isfinite(value) else (str(int(value)) if channel.unit == "bool" else f"{value:.8g}")
            cell = self.readings.item(row, 1)
            cell.setText(text)
            cell.setToolTip(errors.get(channel.key, ""))
        status = f"{len(errors)} unavailable AUX values (hover N/A)" if errors else "Live"
        self.monitor_status.setText(timestamp + " | " + status)
        self.refresh_plots()

    def refresh_plots(self, *_args):
        times = [row[1] for row in self.history]
        for selector, plot, curve in self.time_views:
            key = selector.currentData()
            channel = FM_CHANNEL_BY_KEY[key]
            plot.setLabel("left", channel.label, units=channel.unit)
            curve.setData(times, [row[2].get(key, math.nan) for row in self.history], connect="finite")

    def clear_history(self):
        self.history.clear()
        self._epoch = time.monotonic()
        self.refresh_plots()

    def copy_live_xy(self):
        # Copy latest *readback*, never silently issue an output command.
        if not self.latest or not self.busy:
            self._log("Start Monitor and read live AUX1/2 before copying XY")
            return
        for control, key in ((self.xy_x, "auxout1"), (self.xy_y, "auxout2")):
            value = self.latest.get(key, math.nan)
            if math.isfinite(value):
                control.setValue(value)

    def move_xy(self):
        if self.moving or self._scan_active or self._external_motion:
            self._log("Manual XY is disabled while another motion is active")
            return
        try:
            adapter = self.adapter()
            adapter.validate_xy(self.xy_x.value(), self.xy_y.value())
        except (RuntimeError, ValueError) as exc:
            self._log(str(exc))
            return
        worker = _XYWorker(adapter, (self.xy_x.value(), self.xy_y.value()), self.xy_speed.value())
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.message.connect(self._log)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._move_finished)
        thread.finished.connect(thread.deleteLater)
        self._move_worker, self._move_thread = worker, thread
        self._update_controls()
        self.activity_changed.emit()
        thread.start()

    def stop_xy(self):
        if self._move_worker is not None:
            self._move_worker.stop.set()

    def _move_finished(self):
        self._move_worker = self._move_thread = None
        self._update_controls()
        self.activity_changed.emit()

    def _update_controls(self):
        monitoring = self._monitor_thread is not None
        self.monitor_start.setEnabled(not monitoring)
        self.monitor_read.setEnabled(not monitoring)
        self.monitor_stop.setEnabled(monitoring)
        self.monitor_interval.setEnabled(not monitoring)
        manual = not self.moving and not self._scan_active and not self._external_motion
        for widget in (self.xy_move, self.xy_x, self.xy_y, self.xy_speed, self.xy_read):
            widget.setEnabled(manual)
        self.xy_stop.setEnabled(self.moving)

    def snapshot(self):
        return {
            "last_sample_utc": self.last_timestamp,
            "latest": {key: value if math.isfinite(value) else None for key, value in self.latest.items()},
            "monitor_interval_ms": self.monitor_interval.value(),
            "history_limit": self.HISTORY_LIMIT,
            "aux_units": "HF2 AUX output V (before external amplifier)",
            "labone_owns": ["PLL", "PID", "excitation"],
        }

    def export_history(self):
        path, _ = QFileDialog.getSaveFileName(self.widget, "Export FM-AFM history", "fm_afm_history.csv", "CSV (*.csv)")
        if path:
            try:
                self.write_history(path)
            except OSError as exc:
                self._log(f"History export failed: {exc}")

    def write_history(self, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp_utc", "elapsed_s", *[f"{c.key} [{c.unit}]" for c in FM_CHANNELS]])
            for timestamp, elapsed, values in list(self.history):
                writer.writerow([timestamp, elapsed, *[values.get(c.key, math.nan) for c in FM_CHANNELS]])
        self._log(f"Saved bounded FM-AFM history: {path}")

    def shutdown(self, timeout_ms=5000):
        self.stop_monitor()
        self.stop_xy()
        deadline = time.monotonic() + timeout_ms / 1000
        for thread in (self._monitor_thread, self._move_thread):
            if thread is not None and not thread.wait(max(0, int((deadline - time.monotonic()) * 1000))):
                return False
        return True


class _MonitorWorker(QObject):
    sample = pyqtSignal(str, float, object, object)
    finished = pyqtSignal()

    def __init__(self, adapter, interval, once):
        super().__init__()
        self.adapter, self.interval, self.once = adapter, interval, once
        self.stop = threading.Event()

    @pyqtSlot()
    def run(self):
        try:
            while not self.stop.is_set():
                begin = time.monotonic()
                try:
                    values = self.adapter.read_fm_snapshot()
                    errors = dict(self.adapter.fm_errors)
                except Exception as exc:
                    values = {c.key: math.nan for c in FM_CHANNELS}
                    errors = {c.key: str(exc) for c in FM_CHANNELS}
                self.sample.emit(datetime.now(timezone.utc).isoformat(timespec="milliseconds"), time.monotonic(), values, errors)
                if self.once or self.stop.wait(max(0.01, self.interval - (time.monotonic() - begin))):
                    break
        finally:
            self.finished.emit()


class _XYWorker(QObject):
    finished = pyqtSignal()
    message = pyqtSignal(str)

    def __init__(self, adapter, target, speed):
        super().__init__()
        self.adapter, self.target, self.speed = adapter, target, speed
        self.stop = threading.Event()

    @pyqtSlot()
    def run(self):
        try:
            self.adapter.validate_xy_control()
            end = ramp_xy(self.adapter, self.adapter.read_xy(), self.target, self.speed, self.stop)
            self.message.emit(f"XY {'stopped' if self.stop.is_set() else 'moved'} at AUX1={end[0]:.6g}, AUX2={end[1]:.6g} V; outputs held")
        except Exception as exc:
            self.message.emit(f"XY move failed: {exc}")
        finally:
            self.finished.emit()
