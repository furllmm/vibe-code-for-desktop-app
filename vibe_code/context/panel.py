from __future__ import annotations

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .models import ContextPack


class ContextPanel(QWidget):
    """Inspectable view of the files selected for the next AI request."""

    def __init__(self) -> None:
        super().__init__()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Context file", "Score", "Why"])
        self.tree.setColumnWidth(0, 280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.tree)

    def show_pack(self, pack: ContextPack) -> None:
        self.tree.clear()
        for item in pack.items:
            self.tree.addTopLevelItem(
                QTreeWidgetItem(
                    [str(item.path), f"{item.score:.1f}", item.reason]
                )
            )
        self.tree.setToolTip(
            f"{len(pack.items)} files selected • ~{pack.estimated_tokens} estimated tokens"
        )
