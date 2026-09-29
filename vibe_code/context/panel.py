from __future__ import annotations

from PySide6.QtWidgets import (
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import ContextPack


class ContextPanel(QWidget):
    """Inspectable view of the files selected for the next AI request."""

    def __init__(self) -> None:
        super().__init__()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Context file", "Score", "Why", "Range"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 260)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setAlternatingRowColors(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.tree)

    def show_pack(self, pack: ContextPack) -> None:
        self.tree.clear()
        for item in pack.items:
            row = QTreeWidgetItem(
                [
                    str(item.path),
                    f"{item.score:.1f}",
                    item.reason,
                    item.line_range,
                ]
            )
            row.setToolTip(0, str(item.path))
            row.setToolTip(1, f"Relevance score: {item.score:.1f}")
            row.setToolTip(2, item.reason)
            if item.line_range:
                row.setToolTip(3, f"Only this symbol range is loaded: {item.line_range}")
            self.tree.addTopLevelItem(row)

        self.tree.setToolTip(
            f"{pack.summary()}. "
            "Scores and reasons explain why each item entered the context."
        )
