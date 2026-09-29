from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
    QHeaderView, QLabel, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from afm_gui.core.fm_afm import FM_CHANNELS


def build_fm_afm_panel(module) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    description = QLabel(
        "HF2LI → AUX1: X / AUX2: Y / AUX3: Z PID / AUX4: PLL Δf\n"
        "PLL/PID/excitation are configured in LabOne. GUI writes AUX1/2 only."
    )
    description.setWordWrap(True)
    layout.addWidget(description)
    controls = QGridLayout()
    module.monitor_start = QPushButton("Start Monitor")
    module.monitor_stop = QPushButton("Stop Monitor")
    module.monitor_read = QPushButton("Read Once")
    module.monitor_export = QPushButton("Export History CSV")
    module.monitor_clear = QPushButton("Clear History")
    module.monitor_interval = QSpinBox()
    module.monitor_interval.setRange(100, 10000)
    module.monitor_interval.setValue(500)
    module.monitor_interval.setSuffix(" ms")
    for column, button in enumerate((module.monitor_start, module.monitor_stop, module.monitor_read)):
        controls.addWidget(button, 0, column)
    controls.addWidget(module.monitor_export, 1, 0)
    controls.addWidget(module.monitor_clear, 1, 1)
    controls.addWidget(module.monitor_interval, 1, 2)
    layout.addLayout(controls)
    module.monitor_status = QLabel("Disconnected / no live data")
    module.monitor_status.setWordWrap(True)
    layout.addWidget(module.monitor_status)

    xy = QGroupBox("Manual XY — HF2 AUX voltage (V), not amplified voltage")
    form = QGridLayout(xy)
    module.xy_x = _spin(0, 5, 2.5)
    module.xy_y = _spin(0, 5, 2.5)
    module.xy_speed = _spin(0.001, 1, 0.05)
    module.xy_move = QPushButton("Move XY")
    module.xy_stop = QPushButton("Stop XY / Hold")
    module.xy_read = QPushButton("Copy Live XY")
    module.xy_limits = QLabel("Software limits: 0…5 V; verify limits for your scanner before use")
    module.xy_limits.setWordWrap(True)
    for col, (name, control) in enumerate((("X (V)", module.xy_x), ("Y (V)", module.xy_y), ("Speed (V/s)", module.xy_speed))):
        form.addWidget(QLabel(name), 0, col)
        form.addWidget(control, 1, col)
    for col, button in enumerate((module.xy_move, module.xy_stop, module.xy_read)):
        form.addWidget(button, 2, col)
    form.addWidget(module.xy_limits, 3, 0, 1, 3)
    layout.addWidget(xy)
    splitter = QSplitter(Qt.Orientation.Vertical)
    module.readings = QTableWidget(len(FM_CHANNELS), 3)
    module.readings.setHorizontalHeaderLabels(("Signal", "Value", "Unit"))
    module.readings.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    module.readings.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for column in (1, 2):
        module.readings.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    module.readings.setMinimumHeight(150)
    for row, channel in enumerate(FM_CHANNELS):
        for col, value in enumerate((channel.label, "N/A", channel.unit)):
            item = QTableWidgetItem(value)
            item.setToolTip(channel.label if col == 0 else value)
            module.readings.setItem(row, col, item)
    splitter.addWidget(module.readings)
    plot_widget = QWidget()
    plots = QVBoxLayout(plot_widget)
    module.time_views = []
    for default in ("auxout3", "auxout4", "pid_error"):
        selector = QComboBox()
        for channel in FM_CHANNELS:
            selector.addItem(f"{channel.label} [{channel.unit}]", channel.key)
        selector.setCurrentIndex(selector.findData(default))
        plot = pg.PlotWidget()
        plot.setMinimumHeight(100)
        plot.setMaximumHeight(125)
        plot.setLabel("bottom", "Elapsed time", units="s")
        plot.showGrid(x=True, y=True, alpha=0.2)
        curve = plot.plot(pen=pg.mkPen("#4dabf7", width=1.5), connect="finite")
        if module.time_views:
            plot.setXLink(module.time_views[0][1])
        module.time_views.append((selector, plot, curve))
        plots.addWidget(selector)
        plots.addWidget(plot)
    splitter.addWidget(plot_widget)
    layout.addWidget(splitter, 1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    scroll.setMinimumWidth(310)
    return scroll


def _spin(lower, upper, initial):
    control = QDoubleSpinBox()
    control.setRange(lower, upper)
    control.setDecimals(5)
    control.setSingleStep(0.01)
    control.setValue(initial)
    return control
