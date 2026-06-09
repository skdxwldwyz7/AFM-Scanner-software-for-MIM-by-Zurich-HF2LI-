from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLineEdit, QPushButton


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
    layout.addWidget(window.auto_save_enabled, 2, 0)
    layout.addWidget(window.auto_save_dir, 2, 1, 1, 2)
    layout.addWidget(window.auto_save_browse, 2, 3)
    return box
