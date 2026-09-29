from afm_gui.startup import ensure_mpl_config_dir

ensure_mpl_config_dir()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from afm_gui.ui.main_window import MainWindow


def main() -> int:
    app = QApplication([])
    app.setApplicationName("AFM Scan Control")
    window = MainWindow()
    window.resize(1600, 900)
    window.show()
    # Restore splitter proportions after Qt has resolved the visible window's
    # geometry; restoring only during construction distorts scrollable docks.
    QTimer.singleShot(0, window.layout_module.load_startup_layout)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
