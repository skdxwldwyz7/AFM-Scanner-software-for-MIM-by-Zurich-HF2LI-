from __future__ import annotations

from PyQt6.QtWidgets import QGroupBox, QPlainTextEdit, QVBoxLayout


MAX_LOG_BLOCKS = 5000


def build_command_log_panel(window) -> QGroupBox:
    box = QGroupBox("Command Log")
    layout = QVBoxLayout(box)
    window.log = QPlainTextEdit()
    window.log.setReadOnly(True)
    window.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    window.log.setMaximumBlockCount(MAX_LOG_BLOCKS)
    layout.addWidget(window.log)
    return box
