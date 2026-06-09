from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def build_approach_panel(module) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setSpacing(6)

    config_box = QGroupBox("Approach")
    config = QFormLayout(config_box)
    config.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    module.approach_actuator = QComboBox()
    module.approach_actuator.addItems(("mock.z", "coarse_stage.z"))
    module.approach_direction = QComboBox()
    module.approach_direction.addItems(("down", "up"))
    module.approach_step = _double(0.000001, 1000.0, 0.05, " um", decimals=6)
    module.approach_settle = _double(0.001, 60.0, 0.05, " s", decimals=4)
    config.addRow("Actuator", module.approach_actuator)
    config.addRow("Direction", module.approach_direction)
    config.addRow("Step", module.approach_step)
    config.addRow("Settle", module.approach_settle)

    signal_box = QGroupBox("Signal")
    signal = QFormLayout(signal_box)
    signal.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    module.approach_signal_device = QComboBox()
    module.approach_signal_device.addItem("mock")
    module.approach_signal_channel = QComboBox()
    module.approach_signal_channel.addItems(("ch1", "ch2"))
    module.approach_signal_quantity = QComboBox()
    module.approach_signal_quantity.addItems(("x", "y", "r", "theta", "frequency", "current", "deflection"))
    module.approach_signal_quantity.setCurrentText("r")
    module.approach_read_signal = QPushButton("Read")
    module.approach_signal_value = QLabel("0")
    signal.addRow("Device", module.approach_signal_device)
    signal.addRow("Channel", module.approach_signal_channel)
    signal.addRow("Quantity", module.approach_signal_quantity)
    signal.addRow("Value", module.approach_signal_value)
    signal.addRow(module.approach_read_signal)

    condition_box = QGroupBox("Stop Condition")
    condition = QFormLayout(condition_box)
    condition.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    module.approach_condition_type = QComboBox()
    module.approach_condition_type.addItems(("above", "below", "delta", "between", "outside"))
    module.approach_threshold = _double(-1e12, 1e12, 1.0, "", decimals=6)
    module.approach_low = _double(-1e12, 1e12, 0.0, "", decimals=6)
    module.approach_high = _double(-1e12, 1e12, 1.0, "", decimals=6)
    module.approach_consecutive = QSpinBox()
    module.approach_consecutive.setRange(1, 1000)
    module.approach_consecutive.setValue(3)
    condition.addRow("Type", module.approach_condition_type)
    condition.addRow("Threshold", module.approach_threshold)
    condition.addRow("Low", module.approach_low)
    condition.addRow("High", module.approach_high)
    condition.addRow("Consecutive", module.approach_consecutive)

    safety_box = QGroupBox("Safety")
    safety = QFormLayout(safety_box)
    safety.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
    module.approach_max_travel = _double(0.000001, 100000.0, 10.0, " um", decimals=6)
    module.approach_max_steps = QSpinBox()
    module.approach_max_steps.setRange(1, 1_000_000)
    module.approach_max_steps.setValue(1000)
    module.approach_retract = _double(0.0, 100000.0, 1.0, " um", decimals=6)
    safety.addRow("Max Travel", module.approach_max_travel)
    safety.addRow("Max Steps", module.approach_max_steps)
    safety.addRow("Retract", module.approach_retract)

    runtime_box = QGroupBox("Runtime")
    runtime = QGridLayout(runtime_box)
    module.approach_state = QLabel("Idle")
    module.approach_steps = QLabel("0")
    module.approach_travel = QLabel("0 um")
    module.approach_hits = QLabel("0")
    module.approach_start = QPushButton("Start")
    module.approach_pause = QPushButton("Pause")
    module.approach_resume = QPushButton("Resume")
    module.approach_abort = QPushButton("Abort")
    module.approach_retract_button = QPushButton("Retract")
    runtime.addWidget(QLabel("State"), 0, 0)
    runtime.addWidget(module.approach_state, 0, 1)
    runtime.addWidget(QLabel("Steps"), 0, 2)
    runtime.addWidget(module.approach_steps, 0, 3)
    runtime.addWidget(QLabel("Travel"), 1, 0)
    runtime.addWidget(module.approach_travel, 1, 1)
    runtime.addWidget(QLabel("Hits"), 1, 2)
    runtime.addWidget(module.approach_hits, 1, 3)
    for index, button in enumerate(
        (
            module.approach_start,
            module.approach_pause,
            module.approach_resume,
            module.approach_abort,
            module.approach_retract_button,
        )
    ):
        runtime.addWidget(button, 2 + index // 3, index % 3)

    top = QGridLayout()
    top.addWidget(config_box, 0, 0)
    top.addWidget(signal_box, 0, 1)
    top.addWidget(condition_box, 1, 0)
    top.addWidget(safety_box, 1, 1)
    layout.addLayout(top)
    layout.addWidget(runtime_box)
    layout.addStretch(1)
    return widget


def _double(minimum: float, maximum: float, value: float, suffix: str, *, decimals: int = 3) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setAlignment(Qt.AlignmentFlag.AlignRight)
    return widget


__all__ = ["build_approach_panel"]
