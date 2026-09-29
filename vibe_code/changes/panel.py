from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vibe_code.changes import ChangeManager


class ChangePanel(QWidget):
    """Inspectable agent changes with a textual diff and safe rollback action."""

    rollback_requested = Signal(str)

    def __init__(self, manager: ChangeManager) -> None:
        super().__init__()
        self.manager = manager
        self.changes = QListWidget()
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.rollback = QPushButton("Revert Selected Change")
        self.rollback.setEnabled(False)
        self.rollback.clicked.connect(self._rollback_selected)
        self.changes.currentItemChanged.connect(self._show_selected)

        splitter = QSplitter()
        splitter.addWidget(self.changes)
        splitter.addWidget(self.diff)
        splitter.setSizes([280, 720])

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.rollback)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        layout.addLayout(buttons)

    def refresh(self) -> None:
        selected = self.changes.currentItem()
        selected_id = selected.data(0, 256) if selected else None
        self.changes.clear()
        for change in self.manager.list_changes():
            item = QListWidgetItem(
                f"{change.id[:12]} — " + ", ".join(c.path for c in change.changes)
            )
            item.setData(256, change.id)
            self.changes.addItem(item)
        if selected_id:
            for index in range(self.changes.count()):
                item = self.changes.item(index)
                if item.data(256) == selected_id:
                    self.changes.setCurrentItem(item)
                    break
        elif self.changes.count():
            self.changes.setCurrentRow(0)
        else:
            self.diff.clear()
            self.rollback.setEnabled(False)

    def _show_selected(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is None:
            self.diff.clear()
            self.rollback.setEnabled(False)
            return
        change_id = current.data(256)
        try:
            self.diff.setPlainText(self.manager.diff(change_id))
            self.rollback.setEnabled(True)
        except (OSError, KeyError, RuntimeError) as exc:
            self.diff.setPlainText(f"Unable to load diff: {exc}")
            self.rollback.setEnabled(False)

    def _rollback_selected(self) -> None:
        current = self.changes.currentItem()
        if current is not None:
            self.rollback_requested.emit(current.data(256))
