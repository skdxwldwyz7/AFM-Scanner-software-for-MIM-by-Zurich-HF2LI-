from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QGroupBox, QTreeWidgetItem

from afm_gui.ui.panels.parameter_tree import build_parameter_tree_panel


class MetadataModule(QObject):
    """Owns the visible parameter tree and metadata refresh behavior."""

    DEFAULT_EXPANDED_PATHS = {"scan", "runtime"}

    def __init__(
        self,
        metadata_provider: Callable[[], dict[str, object]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._metadata_provider = metadata_provider
        self.widget = build_parameter_tree_panel(self)

    def refresh(self) -> None:
        expanded = self._expanded_paths()
        self.metadata_tree.clear()
        self._add_tree_items(self.metadata_tree.invisibleRootItem(), self._metadata_provider())
        self._restore_expanded_paths(expanded)
        self.metadata_tree.resizeColumnToContents(0)

    def _add_tree_items(self, parent: QTreeWidgetItem, value: object) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            item = QTreeWidgetItem(parent, [str(key), "" if isinstance(child, (dict, list)) else str(child)])
            if isinstance(child, dict):
                self._add_tree_items(item, child)
            elif isinstance(child, list):
                for index, entry in enumerate(child):
                    row = QTreeWidgetItem(item, [str(index), "" if isinstance(entry, dict) else str(entry)])
                    if isinstance(entry, dict):
                        self._add_tree_items(row, entry)

    def _expanded_paths(self) -> set[str]:
        paths = set()

        def walk(item: QTreeWidgetItem, prefix: str = "") -> None:
            for index in range(item.childCount()):
                child = item.child(index)
                path = f"{prefix}.{child.text(0)}" if prefix else child.text(0)
                if child.isExpanded():
                    paths.add(path)
                walk(child, path)

        walk(self.metadata_tree.invisibleRootItem())
        return paths

    def _restore_expanded_paths(self, paths: set[str]) -> None:
        def walk(item: QTreeWidgetItem, prefix: str = "") -> None:
            for index in range(item.childCount()):
                child = item.child(index)
                path = f"{prefix}.{child.text(0)}" if prefix else child.text(0)
                child.setExpanded(path in paths or path in self.DEFAULT_EXPANDED_PATHS)
                walk(child, path)

        walk(self.metadata_tree.invisibleRootItem())


__all__ = ["MetadataModule"]
