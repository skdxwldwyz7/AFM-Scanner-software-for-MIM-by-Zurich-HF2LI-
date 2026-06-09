from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from afm_gui.core.approach_config import ApproachConfig, evaluate_approach_condition


ActuatorCallback = Callable[[float], None]
SignalCallback = Callable[[], float]


@dataclass(slots=True)
class ApproachProgress:
    state: str = "Idle"
    steps: int = 0
    travel_um: float = 0.0
    signal_value: float = 0.0
    consecutive_hits: int = 0
    message: str = ""


class MockApproachPlant:
    """Small deterministic plant for offline approach bringup."""

    def __init__(self) -> None:
        self.position_um = 0.0

    def move_relative(self, dz_um: float) -> None:
        self.position_um += float(dz_um)

    def signal(self) -> float:
        return max(0.0, abs(self.position_um) * 10.0)


class ApproachController(QObject):
    progress_changed = pyqtSignal(object)
    state_changed = pyqtSignal(str)
    log_message = pyqtSignal(str)

    def __init__(
        self,
        actuator_provider: Callable[[], ActuatorCallback] | None = None,
        signal_provider: Callable[[], SignalCallback] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._mock = MockApproachPlant()
        self._actuator_provider = actuator_provider or (lambda: self._mock.move_relative)
        self._signal_provider = signal_provider or (lambda: self._mock.signal)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self.config = ApproachConfig()
        self.progress = ApproachProgress()
        self._running = False
        self._paused = False
        self._baseline = 0.0
        self._actuator: ActuatorCallback | None = None
        self._read_signal: SignalCallback | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self, config: ApproachConfig) -> None:
        if self._running:
            return
        self.config = config
        try:
            self._actuator = self._actuator_provider()
            self._read_signal = self._signal_provider()
            self._baseline = float(self._read_signal())
        except Exception as exc:
            self._actuator = None
            self._read_signal = None
            self._running = False
            self._paused = False
            self.progress = ApproachProgress(state="Failed", message=str(exc))
            self._emit_progress(f"Approach failed: {exc}")
            return
        self.progress = ApproachProgress(state="Approaching", signal_value=self._baseline)
        self._running = True
        self._paused = False
        self._emit_progress("Approach started")
        self._timer.start(int(max(1.0, config.settle_s * 1000.0)))

    def pause(self) -> None:
        if not self._running or self._paused:
            return
        self._timer.stop()
        self._paused = True
        self.progress.state = "Paused"
        self._emit_progress("Approach paused")

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        self._paused = False
        self.progress.state = "Approaching"
        self._timer.start(int(max(1.0, self.config.settle_s * 1000.0)))
        self._emit_progress("Approach resumed")

    def abort(self, *, message: str = "Approach aborted") -> None:
        if not self._running and not self._paused:
            return
        self._timer.stop()
        self._running = False
        self._paused = False
        self.progress.state = "Aborted"
        self._emit_progress(message)

    def retract(self, distance_um: float | None = None) -> None:
        distance = self.config.safety.retract_on_fail_um if distance_um is None else float(distance_um)
        direction = 1.0 if self.config.direction == "down" else -1.0
        try:
            actuator = self._actuator_provider()
            actuator(direction * abs(distance))
        except Exception as exc:
            self.progress.state = "Failed"
            self._emit_progress(f"Retract failed: {exc}")
            return
        self.progress.state = "Retracted"
        self.progress.travel_um = max(0.0, self.progress.travel_um - abs(distance))
        self._emit_progress(f"Retracted {abs(distance):.6g} um")

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self.progress.state,
            "steps": self.progress.steps,
            "travel_um": self.progress.travel_um,
            "signal_value": self.progress.signal_value,
            "consecutive_hits": self.progress.consecutive_hits,
            "config": {
                "name": self.config.name,
                "actuator": self.config.actuator,
                "direction": self.config.direction,
                "step_um": self.config.step_um,
                "settle_s": self.config.settle_s,
                "signal": {
                    "device": self.config.signal.device,
                    "channel": self.config.signal.channel,
                    "quantity": self.config.signal.quantity,
                },
                "condition": {
                    "type": self.config.condition.condition_type,
                    "threshold": self.config.condition.threshold,
                    "low": self.config.condition.low,
                    "high": self.config.condition.high,
                    "consecutive": self.config.condition.consecutive,
                },
                "safety": {
                    "max_travel_um": self.config.safety.max_travel_um,
                    "max_steps": self.config.safety.max_steps,
                    "retract_on_fail_um": self.config.safety.retract_on_fail_um,
                },
            },
        }

    def _step(self) -> None:
        if self._actuator is None or self._read_signal is None:
            self.abort(message="Approach provider is not available")
            return
        step = abs(float(self.config.step_um))
        dz = -step if self.config.direction == "down" else step
        try:
            self._actuator(dz)
        except Exception as exc:
            self._fail(f"Approach actuator failed: {exc}")
            return
        self.progress.steps += 1
        self.progress.travel_um += step
        try:
            self.progress.signal_value = float(self._read_signal())
        except Exception as exc:
            self._fail(f"Approach signal read failed: {exc}")
            return

        hit = evaluate_approach_condition(
            self.progress.signal_value,
            self.config.condition,
            baseline=self._baseline,
        )
        self.progress.consecutive_hits = self.progress.consecutive_hits + 1 if hit else 0

        if self.progress.consecutive_hits >= max(1, int(self.config.condition.consecutive)):
            self._timer.stop()
            self._running = False
            self.progress.state = "Complete"
            self._emit_progress("Approach complete")
            return

        if self.progress.travel_um >= float(self.config.safety.max_travel_um):
            self._fail("Approach failed: max travel reached")
            return
        if self.progress.steps >= int(self.config.safety.max_steps):
            self._fail("Approach failed: max steps reached")
            return
        self._emit_progress("Approaching")

    def _fail(self, message: str) -> None:
        self._timer.stop()
        self._running = False
        self._paused = False
        self.progress.state = "Failed"
        self._emit_progress(message)

    def _emit_progress(self, message: str) -> None:
        self.progress.message = message
        self.progress_changed.emit(self.progress)
        self.state_changed.emit(self.progress.state)
        self.log_message.emit(message)


__all__ = [
    "ActuatorCallback",
    "ApproachController",
    "ApproachProgress",
    "MockApproachPlant",
    "SignalCallback",
]
