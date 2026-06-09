from __future__ import annotations

import hashlib

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from qcodes.instrument import Instrument


class MockAFMInstrument(Instrument):
    """Small QCoDeS instrument shell for GUI development without hardware."""

    def __init__(self, name: str = "mock_afm") -> None:
        super().__init__(name)
        self.add_parameter("x_nm", initial_value=0.0, get_cmd=None, set_cmd=None)
        self.add_parameter("y_nm", initial_value=0.0, get_cmd=None, set_cmd=None)


class MockScannerDevice(QObject):
    line_data_ready = pyqtSignal(int, object)
    command_logged = pyqtSignal(str)
    scan_finished = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.instrument = MockAFMInstrument()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._emit_line)
        self._line_index = 0
        self._line_count = 0
        self._pixels = 0
        self._channels: tuple[str, ...] = ()
        self._rng = np.random.default_rng(42)

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
        self._line_index = 0
        self._line_count = line_count
        self._pixels = pixels
        self._channels = channels
        self._timer.start(max(20, interval_ms))

    def pause(self) -> None:
        self._timer.stop()

    def resume(self, interval_ms: int) -> None:
        self._timer.start(max(20, interval_ms))

    def set_line_interval(self, interval_ms: int) -> None:
        if self._timer.isActive():
            self._timer.setInterval(max(20, interval_ms))

    def stop(self) -> None:
        self._timer.stop()
        self.scan_finished.emit()

    def _emit_line(self) -> None:
        if self._line_index >= self._line_count:
            self.stop()
            return

        x = np.linspace(-1.0, 1.0, self._pixels)
        y = self._line_index / max(self._line_count - 1, 1)
        surface = 0.35 * np.sin(8 * x + 8 * y) + 0.65 * np.exp(-5 * (x**2 + (y - 0.5) ** 2))
        slope = np.gradient(surface)
        channel_data = {
            "topography": surface + self._rng.normal(0.0, 0.025, self._pixels),
            "error": slope + self._rng.normal(0.0, 0.01, self._pixels),
            "amplitude": 1.0 + 0.08 * np.sin(10 * x - 4 * y) + self._rng.normal(0.0, 0.01, self._pixels),
            "phase": 20.0 * np.cos(4 * x + 6 * y) + self._rng.normal(0.0, 0.8, self._pixels),
            "current": 1e-9 * (1.0 + surface + self._rng.normal(0.0, 0.03, self._pixels)),
            "didv": 1e-9 * (0.5 + np.abs(slope) + self._rng.normal(0.0, 0.02, self._pixels)),
            "bias": np.linspace(-1.0, 1.0, self._pixels),
            "lift_height": 40.0 + 3.0 * np.sin(5 * x + y),
            "magnetic_phase": 8.0 * np.sin(3 * x - 5 * y) + self._rng.normal(0.0, 0.5, self._pixels),
        }
        selected = {}
        for name in self._channels:
            trace = channel_data.get(name, self._synthetic_channel(name, x, y))
            retrace = trace[::-1] + self._rng.normal(0.0, max(np.nanstd(trace), 1e-9) * 0.02, self._pixels)
            selected[name] = {
                "trace": trace,
                "retrace": retrace,
            }
        self.line_data_ready.emit(self._line_index, selected)
        self._line_index += 1

    def _synthetic_channel(self, name: str, x: np.ndarray, y: float) -> np.ndarray:
        digest = hashlib.sha256(name.encode("utf-8")).digest()
        frequency = 2 + digest[0] % 9
        phase = digest[1] / 255.0 * 2.0 * np.pi
        scale = 0.1 + digest[2] / 255.0
        noise = self._rng.normal(0.0, 0.02 * scale, self._pixels)
        return scale * np.sin(frequency * x + phase + 4 * y) + noise
