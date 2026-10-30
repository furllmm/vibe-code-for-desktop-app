from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Signal, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QPlainTextEdit, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from vibe_code.workspace import Workspace


MAX_EDITABLE_FILE_BYTES = 2 * 1024 * 1024


class CodeHighlighter(QSyntaxHighlighter):
    """Lightweight lexical syntax highlighting for common source formats."""

    _KEYWORDS = {
        ".py": "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield",
        ".js": "async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof var void while with yield",
        ".ts": "abstract any as async await boolean break case catch class const continue declare default delete do else enum export extends false finally for from function if implements import in interface let new null number of private protected public readonly return static string super switch this throw true try type typeof var void while",
        ".c": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while",
        ".h": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while",
        ".cpp": "alignas auto bool break case catch char class const constexpr continue decltype default delete do double else enum explicit export extern false float for friend goto if inline int long namespace new noexcept nullptr operator private protected public register return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while",
        ".java": "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new package private protected public return short static strictfp super switch synchronized this throw throws transient try void volatile while",
        ".json": "true false null",
    }

    def __init__(self, document, suffix: str) -> None:
        super().__init__(document)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._add(r"\b\d+(?:\.\d+)?\b", "#b5cea8")
        if suffix in self._KEYWORDS:
            words = "|".join(re.escape(word) for word in self._KEYWORDS[suffix].split())
            self._add(rf"\b(?:{words})\b", "#569cd6", bold=True)
        if suffix in {".py", ".sh", ".yaml", ".yml", ".toml", ".rb"}:
            self._add(r"#[^\n]*", "#6a9955", italic=True)
        elif suffix in {".js", ".ts", ".c", ".h", ".cpp", ".java"}:
            self._add(r"//[^\n]*", "#6a9955", italic=True)
            self._add(r"/\*.*?\*/", "#6a9955", italic=True)
        self._add(r'"(?:\\.|[^"\\])*"', "#ce9178")
        if suffix not in {".json", ".xml", ".html", ".htm"}:
            self._add(r"'(?:\\.|[^'\\])*'", "#ce9178")
        if suffix in {".md", ".markdown"}:
            self._add(r"^#{1,6} .*", "#569cd6", bold=True)
            self._add(r"\*\*[^*]+\*\*", "#dcdcaa", bold=True)

    def _add(self, pattern: str, color: str, *, bold: bool = False, italic: bool = False) -> None:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        self.rules.append((QRegularExpression(pattern), fmt))

    def highlightBlock(self, text: str) -> None:
        for expression, fmt in self.rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    find_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setFont(QFont("monospace", 10))
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.line_number_area.setGeometry(
            rect.left(), rect.top(), self.line_number_area_width(), rect.height()
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self.palette().alternateBase())
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self.palette().text().color())
                painter.drawText(
                    0, top, self.line_number_area.width() - 5,
                    self.fontMetrics().height(),  Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(self.palette().alternateBase())
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)

    def go_to_line(self, line_number: int) -> bool:
        if line_number < 1 or line_number > self.blockCount():
            return False
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.MoveAnchor, line_number - 1)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()
        return True

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Find):
            self.find_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Find):
            self.find_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class EditorPanel(QWidget):
    """Workspace-confined, tabbed text editor with explicit save/discard prompts."""

    status_message = Signal(str)

    def __init__(self, workspace: Workspace, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._paths: dict[int, Path] = {}
        self._editors: dict[int, CodeEditor] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        find_row = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in current file…")
        self.find_input.returnPressed.connect(self.find_next)
        self.find_next_button = QPushButton("Next")
        self.find_next_button.clicked.connect(self.find_next)
        self.find_status = QLabel("")
        find_row.addWidget(self.find_input, 1)
        find_row.addWidget(self.find_next_button)
        find_row.addWidget(self.find_status)
        layout.addLayout(find_row)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.currentChanged.connect(self._reindex_tabs)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.tabs, 1)
        self.find_input.hide()
        self.find_next_button.hide()
        self.find_status.hide()

    def _resolve_file(self, path: str | Path) -> Path:
        resolved = self.workspace.resolve(path)
        if not resolved.exists() or not resolved.is_file():
            raise ValueError("Only existing regular files can be opened")
        if resolved.stat().st_size > MAX_EDITABLE_FILE_BYTES:
            raise ValueError("File exceeds the 2 MiB editor limit")
        return resolved

    def open_file(self, path: str | Path) -> CodeEditor:
        resolved = self._resolve_file(path)
        for index in range(self.tabs.count()):
            if self._paths.get(index) == resolved:
                self.tabs.setCurrentIndex(index)
                return self._editors[index]

        raw = resolved.read_bytes()
        if b"\x00" in raw:
            raise ValueError("Binary files cannot be opened in the text editor")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("File is not valid UTF-8 text") from exc

        editor = CodeEditor()
        editor._workspace_path = resolved
        editor._disk_hash = hashlib.sha256(raw).hexdigest()
        editor.setPlainText(content)
        CodeHighlighter(editor.document(), resolved.suffix.lower())
        editor.document().modificationChanged.connect(
            lambda _modified, widget=editor: self._update_tab_title(widget)
        )
        editor.find_requested.connect(self.show_find)
        index = self.tabs.addTab(editor, resolved.name)
        self._paths[index] = resolved
        self._editors[index] = editor
        self.tabs.setTabToolTip(index, str(resolved))
        self.tabs.setCurrentIndex(index)
        self.status_message.emit(f"Opened {resolved.relative_to(self.workspace.root)}")
        return editor

    def _reindex_tabs(self, _index: int = -1) -> None:
        paths: dict[int, Path] = {}
        editors: dict[int, CodeEditor] = {}
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if not isinstance(widget, CodeEditor):
                continue
            path = getattr(widget, "_workspace_path", None)
            if path is not None:
                paths[index] = path
                editors[index] = widget
        self._paths, self._editors = paths, editors

    def _update_tab_title(self, editor: CodeEditor) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.widget(index) is editor:
                path = self._paths.get(index)
                if path is None:
                    self._reindex_tabs()
                    path = self._paths.get(index)
                if path is not None:
                    self.tabs.setTabText(index, path.name + (" •" if editor.document().isModified() else ""))
                return

    def save_current(self) -> bool:
        index = self.tabs.currentIndex()
        editor = self._editors.get(index)
        path = self._paths.get(index)
        if editor is None or path is None:
            self.status_message.emit("No file is open")
            return False
        try:
            path = self.workspace.resolve(path)
            if not path.exists():
                raise ValueError("File was removed outside the editor. Reopen the workspace before saving.")
            if not path.is_file():
                raise ValueError("Save target is not a regular file")
            payload = editor.toPlainText().encode("utf-8")
            if path.exists():
                current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                if current_hash != getattr(editor, "_disk_hash", current_hash):
                    raise ValueError("File changed outside the editor. Reopen it before saving to avoid overwriting external changes.")
                mode = path.stat().st_mode & 0o777
            else:
                mode = 0o644
            fd, temp_name = tempfile.mkstemp(prefix=".vibe-code-save-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temp_name, mode)
                os.replace(temp_name, path)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            self.status_message.emit(f"Save failed: {exc}")
            return False
        editor._disk_hash = hashlib.sha256(payload).hexdigest()
        editor.document().setModified(False)
        self.status_message.emit(f"Saved {path.relative_to(self.workspace.root)}")
        return True

    def save_all(self) -> bool:
        current = self.tabs.currentIndex()
        for index in range(self.tabs.count()):
            if index != current:
                self.tabs.setCurrentIndex(index)
                editor = self._editors.get(index)
                if editor is not None and editor.document().isModified() and not self.save_current():
                    self.tabs.setCurrentIndex(current)
                    return False
        self.tabs.setCurrentIndex(current)
        editor = self.tabs.currentWidget()
        return self.save_current() if isinstance(editor, CodeEditor) and editor.document().isModified() else True

    def close_tab(self, index: int) -> bool:
        editor = self._editors.get(index)
        path = self._paths.get(index)
        if editor is not None and editor.document().isModified():
            answer = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {path.name if path else 'this file'}?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                self.tabs.setCurrentIndex(index)
                if not self.save_current():
                    return False
        self.tabs.removeTab(index)
        self._reindex_tabs()
        return True

    def confirm_close_all(self) -> bool:
        for index in range(self.tabs.count() - 1, -1, -1):
            if not self.close_tab(index):
                return False
        return True

    def show_find(self) -> None:
        self.find_input.show()
        self.find_next_button.show()
        self.find_status.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def find_next(self) -> None:
        editor = self.tabs.currentWidget()
        query = self.find_input.text()
        if not isinstance(editor, CodeEditor) or not query:
            self.find_status.setText("")
            return
        if not editor.find(query):
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            if not editor.find(query):
                self.find_status.setText("Not found")
                return
        self.find_status.setText("Found")

    def go_to_line(self, line_number: int) -> bool:
        editor = self.tabs.currentWidget()
        if not isinstance(editor, CodeEditor):
            return False
        return editor.go_to_line(line_number)
