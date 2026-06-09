from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from importlib import resources

from pyqtgraph.dockarea import Dock, DockArea
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFileDialog, QMenu, QMessageBox, QWidget


class WindowLayoutModule:
    """Owns dock panel visibility, floating windows, and layout persistence."""

    def __init__(
        self,
        window: QWidget,
        dock_area: DockArea,
        log_callback: Callable[[str], None],
        *,
        startup_layout: str,
        toggle_metadata,
    ) -> None:
        self.window = window
        self.dock_area = dock_area
        self._log_callback = log_callback
        self.startup_layout = startup_layout
        self.toggle_metadata = toggle_metadata
        self.panel_actions: dict[str, QAction] = {}
        self.panels: dict[str, dict[str, object]] = {}
        self.floating_panel_windows: dict[QWidget, str] = {}
        self.default_layout_state: dict[str, object] = {}

    def register_panels(self, panels: dict[str, dict[str, object]]) -> None:
        self.panels = panels
        for key, panel in self.panels.items():
            dock = panel["dock"]
            if isinstance(dock, Dock):
                dock.sigClosed.connect(lambda _dock, panel_key=key: self.sync_panel_action(panel_key, False))
                if panel.get("context_close"):
                    self._install_panel_context_menu(key, dock)

    def build_view_menu(self, view_menu) -> None:
        self.panel_actions = {}
        for key, panel in self.panels.items():
            action = QAction(str(panel["title"]), self.window)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(lambda checked, panel_key=key: self.set_panel_visible(panel_key, checked))
            view_menu.addAction(action)
            self.panel_actions[key] = action

        view_menu.addSeparator()
        show_all = QAction("Show All Panels", self.window)
        show_all.triggered.connect(self.show_all_panels)
        view_menu.addAction(show_all)
        restore_default = QAction("Restore Default Layout", self.window)
        restore_default.triggered.connect(self.restore_default_layout)
        view_menu.addAction(restore_default)
        view_menu.addSeparator()
        save_layout = QAction("Save Layout As...", self.window)
        save_layout.triggered.connect(self.save_layout_as)
        view_menu.addAction(save_layout)
        load_layout = QAction("Load Layout...", self.window)
        load_layout.triggered.connect(self.load_layout)
        view_menu.addAction(load_layout)

    def load_startup_layout(self) -> None:
        path = self.startup_layout_path()
        if not path.exists():
            self._log_callback(f"Startup layout not found: {path}")
            return
        try:
            self.apply_startup_layout()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._log_callback(f"Could not load startup layout {path}: {exc}")
            self.restore_code_default_layout()
            return
        self._log_callback(f"Loaded startup layout: {path}")

    def apply_startup_layout(self) -> None:
        path = self.startup_layout_path()
        if not path.exists():
            raise OSError(f"Startup layout not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.apply_layout_payload(payload)

    def apply_layout_payload(self, payload: dict[str, object]) -> None:
        if payload.get("schema") != "afm_gui.layout.v1":
            raise ValueError("This is not an AFM GUI layout file.")
        self.show_all_panels(allow_floating=False)
        dock_state = payload.get("dock_state")
        if not isinstance(dock_state, dict):
            raise ValueError("Layout file is missing dock_state.")
        self.dock_area.restoreState(dock_state, missing="ignore")
        visible_panels = payload.get("visible_panels", {})
        if not isinstance(visible_panels, dict):
            visible_panels = {}
        for key, panel in self.panels.items():
            visible = bool(visible_panels.get(key, panel.get("default_visible", True)))
            self.set_panel_visible(key, visible, allow_floating=bool(panel.get("open_floating")))
            self.sync_panel_action(key, visible)

    def restore_default_layout(self) -> None:
        try:
            self.apply_startup_layout()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._log_callback(f"Could not restore startup layout: {exc}")
            self.restore_code_default_layout()
            return
        self._log_callback(f"Restored startup layout: {self.startup_layout_path()}")

    def restore_code_default_layout(self) -> None:
        self.show_all_panels(allow_floating=False)
        self.dock_area.restoreState(self.default_layout_state, missing="ignore")
        self.show_all_panels(allow_floating=False)
        self._log_callback("Restored fallback layout")

    def save_layout_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.window,
            "Save Layout",
            str(self.layout_dir() / "layout.json"),
            "AFM Layout (*.json)",
        )
        if not path:
            return
        payload = {
            "schema": "afm_gui.layout.v1",
            "dock_state": self.dock_area.saveState(),
            "visible_panels": {key: self.panel_is_visible(key) for key in self.panels},
        }
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._log_callback(f"Saved layout: {path_obj}")

    def load_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Load Layout",
            str(self.layout_dir()),
            "AFM Layout (*.json)",
        )
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            self.apply_layout_payload(payload)
        except ValueError as exc:
            QMessageBox.warning(self.window, "Load Layout", str(exc))
            return
        self._log_callback(f"Loaded layout: {path}")

    def set_panel_visible(self, key: str, visible: bool, *, allow_floating: bool = True) -> None:
        panel = self.panels[key]
        dock = panel["dock"]
        if not isinstance(dock, Dock):
            return

        if visible:
            if getattr(dock, "_container", None) is None:
                relative_key = panel["relative"]
                relative = self.panels[relative_key]["dock"] if relative_key else None
                self.dock_area.addDock(dock, str(panel["position"]), relative)
            dock.setHidden(False)
            if allow_floating and panel.get("open_floating"):
                dock.float()
                self.track_floating_panel(key)
        else:
            if panel.get("open_floating") and self.panel_is_floating(key):
                self.close_floating_panel(key)
            else:
                dock.setHidden(True)
        if key == "metadata":
            self.toggle_metadata.setText("Hide Metadata" if visible else "Show Metadata")

    def panel_is_floating(self, key: str) -> bool:
        dock = self.panels[key]["dock"]
        return isinstance(dock, Dock) and getattr(dock, "area", None) not in (None, self.dock_area)

    def panel_is_visible(self, key: str) -> bool:
        dock = self.panels[key]["dock"]
        return isinstance(dock, Dock) and getattr(dock, "_container", None) is not None and not dock.isHidden()

    def show_all_panels(self, *, allow_floating: bool = True) -> None:
        for key in self.panels:
            self.set_panel_visible(key, True, allow_floating=allow_floating)
            self.sync_panel_action(key, True)

    def sync_panel_action(self, key: str, visible: bool) -> None:
        action = self.panel_actions.get(key)
        if action is None:
            return
        action.blockSignals(True)
        action.setChecked(visible)
        action.blockSignals(False)
        if key == "metadata":
            self.toggle_metadata.setText("Hide Metadata" if visible else "Show Metadata")

    def track_floating_panel(self, key: str) -> None:
        dock = self.panels[key]["dock"]
        area = getattr(dock, "area", None)
        if not isinstance(dock, Dock) or area in (None, self.dock_area):
            return
        window = getattr(area, "win", None)
        if not isinstance(window, QWidget):
            window = area.window()
        if not isinstance(window, QWidget) or window in self.floating_panel_windows:
            return
        self.floating_panel_windows[window] = key
        window.installEventFilter(self.window)
        window.destroyed.connect(lambda _obj=None, watched=window: self.floating_panel_windows.pop(watched, None))

    def close_floating_panel(self, key: str) -> None:
        dock = self.panels[key]["dock"]
        area = getattr(dock, "area", None)
        window = getattr(area, "win", None) if area is not None else None
        if not isinstance(window, QWidget) and area is not None:
            window = area.window()
        if isinstance(dock, Dock) and getattr(dock, "_container", None) is not None:
            dock.close()
        self.sync_panel_action(key, False)
        if isinstance(window, QWidget):
            window.close()

    def event_filter(self, watched: object, event: QEvent) -> None:
        if event.type() == QEvent.Type.Close and isinstance(watched, QWidget):
            key = self.floating_panel_windows.pop(watched, None)
            if key is not None:
                dock = self.panels[key]["dock"]
                if isinstance(dock, Dock) and self.panel_is_floating(key):
                    dock.close()
                self.sync_panel_action(key, False)

    def _install_panel_context_menu(self, key: str, dock: Dock) -> None:
        dock.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        dock.customContextMenuRequested.connect(
            lambda position, panel_key=key, panel_dock=dock: self._show_panel_context_menu(
                panel_key,
                panel_dock.mapToGlobal(position),
            )
        )

    def _show_panel_context_menu(self, key: str, global_position) -> None:
        panel = self.panels.get(key)
        if panel is None:
            return
        menu = QMenu(self.window)
        close_action = menu.addAction(f"Close {panel['title']}")
        close_action.triggered.connect(lambda _checked=False, panel_key=key: self._close_panel_from_context(panel_key))
        menu.exec(global_position)

    def _close_panel_from_context(self, key: str) -> None:
        self.set_panel_visible(key, False)
        self.sync_panel_action(key, False)

    def startup_layout_path(self) -> Path:
        return Path(str(resources.files("afm_gui.config").joinpath(self.startup_layout)))

    @staticmethod
    def layout_dir() -> Path:
        return Path.home() / ".afm_gui" / "layouts"


__all__ = ["WindowLayoutModule"]
