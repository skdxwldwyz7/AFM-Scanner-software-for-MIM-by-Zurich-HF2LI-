from afm_gui.startup import ensure_mpl_config_dir

ensure_mpl_config_dir()

from PyQt6.QtWidgets import QApplication

from afm_gui.ui.main_window import MainWindow


def main() -> int:
    app = QApplication([])
    app.setApplicationName("AFM Scan Control")
    window = MainWindow()
    window.resize(1280, 780)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
