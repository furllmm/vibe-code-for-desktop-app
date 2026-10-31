from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .indexer import ProjectIndex

_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_LINE = Qt.ItemDataRole.UserRole + 1


class IndexPanel(QWidget):
    """Inspect the structural project index: files, symbols and dependency links."""

    open_requested = Signal(Path, int)

    def __init__(self) -> None:
        super().__init__()
        self._index: ProjectIndex | None = None
        self.stats = QLabel("No index yet — open a workspace")
        self.stats.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter files or symbols…")
        self.search.textChanged.connect(self._populate)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File / symbol", "Kind", "Line"])
        self.tree.setColumnWidth(0, 260)
        self.tree.itemSelectionChanged.connect(self._show_relations)
        self.tree.itemDoubleClicked.connect(self._activate)
        self.relations = QPlainTextEdit()
        self.relations.setReadOnly(True)
        self.relations.setPlaceholderText("Select a file to see its dependencies and dependents")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.relations)
        splitter.setSizes([400, 140])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.stats)
        layout.addWidget(self.search)
        layout.addWidget(splitter)

    def show_index(self, index: ProjectIndex | None) -> None:
        self._index = index
        self.stats.setText(index.stats.summary() if index is not None else "Index unavailable")
        self._populate()

    def _populate(self) -> None:
        self.tree.clear()
        self.relations.clear()
        if self._index is None:
            return
        needle = self.search.text().strip().casefold()
        for relative, item in sorted(self._index.files.items()):
            symbols = item.symbols
            if needle and needle not in relative.casefold():
                symbols = tuple(s for s in symbols if needle in s.qualified_name.casefold())
                if not symbols:
                    continue
            row = QTreeWidgetItem([relative, item.language, ""])
            row.setData(0, _ROLE_PATH, relative)
            row.setData(0, _ROLE_LINE, 1)
            for symbol in symbols:
                child = QTreeWidgetItem([symbol.qualified_name, symbol.kind, str(symbol.line)])
                child.setData(0, _ROLE_PATH, relative)
                child.setData(0, _ROLE_LINE, symbol.line)
                row.addChild(child)
            self.tree.addTopLevelItem(row)
            if needle:
                row.setExpanded(True)

    def _show_relations(self) -> None:
        items = self.tree.selectedItems()
        if not items or self._index is None:
            self.relations.clear()
            return
        relative = items[0].data(0, _ROLE_PATH)
        deps = self._index.dependencies.get(relative, ())
        users = self._index.dependents.get(relative, ())
        changes = self._index.change_counts.get(relative, 0)
        lines = [relative, f"Recent commits touching this file: {changes}", "", "Depends on:"]
        lines += [f"  {d}" for d in deps] or ["  (none)"]
        lines += ["", "Used by:"]
        lines += [f"  {u}" for u in users] or ["  (none)"]
        self.relations.setPlainText("\n".join(lines))

    def _activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        if self._index is None:
            return
        relative = item.data(0, _ROLE_PATH)
        if relative:
            self.open_requested.emit(self._index.root / relative, int(item.data(0, _ROLE_LINE) or 1))
