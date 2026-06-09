from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSpinBox


def build_controls_panel(window) -> QGroupBox:
    box = QGroupBox("Controls")
    layout = QGridLayout(box)
    window.scan_up = QPushButton("Scan Up")
    window.scan_down = QPushButton("Scan Down")
    window.pause = QPushButton("Pause")
    window.resume = QPushButton("Resume")
    window.stop = QPushButton("Stop")
    window.save_gsf = QPushButton("Save GSF")
    window.toggle_metadata = QPushButton("Hide Metadata")
    window.scan_repeat_mode = QComboBox()
    window.scan_repeat_mode.addItem("Single", "single")
    window.scan_repeat_mode.addItem("Continuous Up/Down", "continuous")
    window.scan_repeat_mode.addItem("Count", "count")
    window.scan_repeat_count = QSpinBox()
    window.scan_repeat_count.setRange(1, 9999)
    window.scan_repeat_count.setValue(2)
    window.scan_repeat_count.setEnabled(False)
    window.auto_save_enabled = QCheckBox("Auto Save")
    window.auto_save_enabled.setChecked(True)
    window.auto_save_dir = QLineEdit(str(Path.home() / "AFM_scans"))
    window.auto_save_browse = QPushButton("Browse")
    buttons = (
        window.scan_up,
        window.scan_down,
        window.pause,
        window.resume,
        window.stop,
        window.save_gsf,
        window.toggle_metadata,
    )
    for index, button in enumerate(buttons):
        layout.addWidget(button, index // 4, index % 4)
    layout.addWidget(QLabel("Repeat"), 2, 0)
    layout.addWidget(window.scan_repeat_mode, 2, 1)
    layout.addWidget(QLabel("Count"), 2, 2)
    layout.addWidget(window.scan_repeat_count, 2, 3)
    layout.addWidget(window.auto_save_enabled, 3, 0)
    layout.addWidget(window.auto_save_dir, 3, 1, 1, 2)
    layout.addWidget(window.auto_save_browse, 3, 3)
    return box
