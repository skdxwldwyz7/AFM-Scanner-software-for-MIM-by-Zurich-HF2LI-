from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject

from afm_gui.core.scan_config import ScanDirection
from afm_gui.core.scan_controller import ScanController


class ScanSequenceModule(QObject):
    """Owns single, counted, and continuous scan sequencing."""

    def __init__(
        self,
        controller: ScanController,
        scan_start: Callable[[int], None],
        log_callback: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._scan_start = scan_start
        self._log_callback = log_callback
        self._active = False
        self._remaining: int | None = 0
        self._next_direction = ScanDirection.UP

    @property
    def active(self) -> bool:
        return self._active

    def bind_controls(self, scan_up, scan_down, stop, repeat_mode, repeat_count) -> None:
        self.scan_up = scan_up
        self.scan_down = scan_down
        self.stop_button = stop
        self.repeat_mode = repeat_mode
        self.repeat_count = repeat_count
        self.scan_up.clicked.connect(lambda: self.start(ScanDirection.UP))
        self.scan_down.clicked.connect(lambda: self.start(ScanDirection.DOWN))
        self.stop_button.clicked.connect(self.stop)
        self.repeat_mode.currentIndexChanged.connect(self.on_repeat_mode_changed)

    def start(self, direction: int) -> None:
        mode = self.repeat_mode.currentData()
        if mode == "continuous":
            remaining = None
        elif mode == "count":
            remaining = max(1, int(self.repeat_count.value()))
        else:
            remaining = 1

        self._active = True
        self._remaining = remaining
        self._next_direction = direction
        self.start_next()

    def start_next(self) -> None:
        if not self._active or self.controller.is_running:
            return
        if self._remaining == 0:
            self._active = False
            return

        direction = self._next_direction
        if self._remaining is not None:
            self._remaining -= 1
        self._next_direction = ScanDirection.DOWN if direction == ScanDirection.UP else ScanDirection.UP
        try:
            self._scan_start(direction)
        except Exception as exc:
            self._active = False
            self._remaining = 0
            self._log_callback(f"Could not start scan: {exc}")
            return
        self._log_scan_status(direction)

    def continue_if_needed(self) -> None:
        if not self._active:
            return
        if self._remaining == 0:
            self._active = False
            self._log_callback("Scan sequence complete")
            return
        self.start_next()

    def stop(self) -> None:
        self._active = False
        self._remaining = 0
        self.controller.stop()

    def on_repeat_mode_changed(self) -> None:
        self.update_controls_enabled(not self.controller.is_running and not self.controller.is_paused)

    def update_controls_enabled(self, idle: bool) -> None:
        self.repeat_mode.setEnabled(idle)
        self.repeat_count.setEnabled(idle and self.repeat_mode.currentData() == "count")

    def _log_scan_status(self, direction: int) -> None:
        direction_label = "up" if direction == ScanDirection.UP else "down"
        if self._remaining is None:
            self._log_callback(f"Scan sequence: started {direction_label} scan, continuous mode")
            return
        self._log_callback(f"Scan sequence: started {direction_label} scan, {self._remaining} remaining")


__all__ = ["ScanSequenceModule"]
