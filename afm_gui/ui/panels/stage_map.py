from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def build_stage_map_panel(window) -> QGroupBox:
    box = QGroupBox("Stage Map")
    layout = QGridLayout(box)

    controls = QWidget()
    controls_layout = QGridLayout(controls)
    controls_layout.setContentsMargins(0, 0, 0, 0)

    position_box = QGroupBox("XYZ Stage")
    position_form = QFormLayout(position_box)
    window.stage_x_label = QLabel("0.000 um")
    window.stage_y_label = QLabel("0.000 um")
    window.stage_z_label = QLabel("0.000 um")
    window.stage_target_x = _double(-100_000, 100_000, 0, " um")
    window.stage_target_y = _double(-100_000, 100_000, 0, " um")
    window.stage_target_z = _double(-100_000, 100_000, 0, " um")
    window.stage_step = _double(0.001, 10_000, 1, " um")
    window.stage_z_step = _double(0.001, 10_000, 1, " um")
    position_form.addRow("X", window.stage_x_label)
    position_form.addRow("Y", window.stage_y_label)
    position_form.addRow("Z", window.stage_z_label)
    position_form.addRow("Target X", window.stage_target_x)
    position_form.addRow("Target Y", window.stage_target_y)
    position_form.addRow("Target Z", window.stage_target_z)
    position_form.addRow("XY Step", window.stage_step)
    position_form.addRow("Z Step", window.stage_z_step)

    jog_box = QGroupBox("Jog")
    jog_layout = QGridLayout(jog_box)
    window.stage_jog_up = QPushButton("+Y")
    window.stage_jog_down = QPushButton("-Y")
    window.stage_jog_left = QPushButton("-X")
    window.stage_jog_right = QPushButton("+X")
    window.stage_move_absolute = QPushButton("Move XY")
    window.stage_move_z_absolute = QPushButton("Move Z")
    window.stage_jog_z_up = QPushButton("+Z")
    window.stage_jog_z_down = QPushButton("-Z")
    window.stage_home = QPushButton("Home")
    window.stage_home_z = QPushButton("Home Z")
    window.stage_clear_path = QPushButton("Clear Path")
    jog_layout.addWidget(window.stage_jog_up, 0, 1)
    jog_layout.addWidget(window.stage_jog_left, 1, 0)
    jog_layout.addWidget(window.stage_move_absolute, 1, 1)
    jog_layout.addWidget(window.stage_jog_right, 1, 2)
    jog_layout.addWidget(window.stage_jog_down, 2, 1)
    jog_layout.addWidget(window.stage_jog_z_up, 0, 3)
    jog_layout.addWidget(window.stage_move_z_absolute, 1, 3)
    jog_layout.addWidget(window.stage_jog_z_down, 2, 3)
    jog_layout.addWidget(window.stage_home, 3, 0)
    jog_layout.addWidget(window.stage_home_z, 3, 1)
    jog_layout.addWidget(window.stage_clear_path, 3, 2, 1, 2)

    controls_layout.addWidget(position_box, 0, 0)
    controls_layout.addWidget(jog_box, 0, 1)
    controls_layout.setColumnStretch(0, 1)
    controls_layout.setColumnStretch(1, 1)

    window.stage_plot = pg.PlotWidget()
    window.stage_plot.setBackground("k")
    window.stage_plot.setAspectLocked(True)
    window.stage_plot.setMinimumHeight(260)
    window.stage_plot.showGrid(x=True, y=True, alpha=0.25)
    window.stage_plot.setLabel("bottom", "X", units="um")
    window.stage_plot.setLabel("left", "Y", units="um")
    window.stage_path_curve = window.stage_plot.plot(pen=pg.mkPen("#4dabf7", width=2))
    window.stage_position_item = pg.ScatterPlotItem(
        size=12,
        brush=pg.mkBrush("#ffd43b"),
        pen=pg.mkPen("#ffffff", width=1),
    )
    window.stage_plot.addItem(window.stage_position_item)

    layout.addWidget(window.stage_plot, 0, 0)
    layout.addWidget(controls, 1, 0)
    layout.setRowStretch(0, 1)
    layout.setRowStretch(1, 0)
    return box


def _double(minimum: float, maximum: float, value: float, suffix: str = "") -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(3)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setAlignment(Qt.AlignmentFlag.AlignRight)
    return widget
