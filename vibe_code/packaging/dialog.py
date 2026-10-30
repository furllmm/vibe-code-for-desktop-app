from __future__ import annotations

import shlex
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .engine import PackagingEngine
from .models import PackageRequest, PackagingPlan, PackagingResult
from .worker import PackagingWorker


class PackagingDialog(QDialog):
    """Small, review-first UI for the packaging backends."""

    _BACKENDS = (
        ("Python / PyInstaller", "pyinstaller"),
        ("C / C++ / CPack", "cpack"),
        ("Java / jpackage", "jpackage"),
        ("Linux / AppImage (prepared AppDir)", "appimage"),
    )
    _FORMATS = {
        "pyinstaller": (("One-folder", "onedir"), ("One-file", "onefile")),
        "cpack": tuple((label, value) for label, value in (
            ("ZIP", "zip"), ("TGZ", "tgz"), ("DEB", "deb"),
            ("RPM", "rpm"), ("NSIS", "nsis"), ("IFW", "ifw"),
            ("DragNDrop", "dragndrop"), ("productbuild", "productbuild"),
        )),
        "jpackage": (("App image", "app-image"),),
        "appimage": (("AppImage", "appimage"),),
    }

    def __init__(self, workspace: Path, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace.resolve()
        self.engine = PackagingEngine(self.workspace)
        self._thread: QThread | None = None
        self._worker: PackagingWorker | None = None
        self._cancel_event: threading.Event | None = None
        self._plan: PackagingPlan | None = None
        self._result: PackagingResult | None = None

        self.setWindowTitle("Package Project")
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.backend = QComboBox()
        for label, key in self._BACKENDS:
            self.backend.addItem(label, key)
        self.name = QLineEdit(self.workspace.name or "DesktopApp")
        self.entrypoint = QLineEdit()
        self.entrypoint.setPlaceholderText("Workspace-relative file or directory")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_entrypoint)
        entry_row = QHBoxLayout()
        entry_row.addWidget(self.entrypoint, 1)
        entry_row.addWidget(browse)
        self.output_dir = QLineEdit("dist")
        self.package_type = QComboBox()
        self.backend.currentIndexChanged.connect(self._update_formats)
        form.addRow("Backend", self.backend)
        form.addRow("Application name", self.name)
        form.addRow("Entry point / AppDir", entry_row)
        form.addRow("Output folder", self.output_dir)
        form.addRow("Format", self.package_type)
        layout.addLayout(form)

        self.trust = QCheckBox(
            "I trust this workspace and allow its build/packaging hooks to execute."
        )
        self.trust.setWordWrap(True)
        layout.addWidget(self.trust)
        self.plan_label = QLabel(
            "Review the generated command before starting. Build scripts can execute code."
        )
        self.plan_label.setWordWrap(True)
        layout.addWidget(self.plan_label)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText("Packaging output will appear here…")
        layout.addWidget(self.logs, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.start_button = QPushButton("Review & Package")
        self.start_button.clicked.connect(self._review_and_start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self._update_formats()

    def _backend_key(self) -> str:
        return str(self.backend.currentData())

    def _update_formats(self) -> None:
        current = self.package_type.currentData()
        self.package_type.clear()
        for label, value in self._FORMATS[self._backend_key()]:
            self.package_type.addItem(label, value)
        index = self.package_type.findData(current)
        if index >= 0:
            self.package_type.setCurrentIndex(index)

    def _browse_entrypoint(self) -> None:
        backend = self._backend_key()
        if backend == "appimage":
            selected = QFileDialog.getExistingDirectory(
                self, "Select prepared AppDir", str(self.workspace)
            )
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self, "Select entrypoint", str(self.workspace)
            )
        if selected:
            try:
                relative = Path(selected).resolve().relative_to(self.workspace)
            except ValueError:
                QMessageBox.warning(
                    self, "Outside workspace", "Select a file or folder inside the workspace."
                )
                return
            self.entrypoint.setText(relative.as_posix())

    def _make_request(self) -> PackageRequest:
        backend = self._backend_key()
        package_type = str(self.package_type.currentData())
        return PackageRequest(
            backend=backend,
            name=self.name.text().strip(),
            output_dir=self.output_dir.text().strip() or "dist",
            entrypoint=self.entrypoint.text().strip() or None,
            one_file=backend == "pyinstaller" and package_type == "onefile",
            package_type=package_type,
        )

    def _review_and_start(self) -> None:
        if self._thread is not None:
            return
        if not self.trust.isChecked():
            QMessageBox.warning(
                self, "Workspace trust required",
                "Packaging runs project-controlled build hooks. Review the project and "
                "confirm that you trust this workspace before continuing.",
            )
            return
        try:
            self._plan = self.engine.create_plan(self._make_request())
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Cannot prepare package", str(exc))
            return
        command = shlex.join(self._plan.command)
        answer = QMessageBox.question(
            self,
            "Review packaging command",
            f"{self._plan.description}\n\nCommand:\n{command}\n\n"
            "Run this command in the selected workspace?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_worker()

    def _start_worker(self) -> None:
        assert self._plan is not None
        self._cancel_event = threading.Event()
        thread = QThread(self)
        worker = PackagingWorker(self.engine, self._plan, self._cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.output.connect(self._append_output)
        worker.finished.connect(self._packaging_finished)
        worker.failed.connect(self._packaging_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.close_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.plan_label.setText("Packaging is running…")
        thread.start()

    def _append_output(self, value: str) -> None:
        self.logs.moveCursor(self.logs.textCursor().MoveOperation.End)
        self.logs.insertPlainText(value)
        self.logs.ensureCursorVisible()

    def _cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.plan_label.setText("Cancellation requested; stopping child processes…")

    def _packaging_finished(self, result: object) -> None:
        if not isinstance(result, PackagingResult):
            self.plan_label.setText("Packaging returned an unexpected result.")
            return
        self._result = result
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if result.success else 0)
        self.plan_label.setText(
            f"Package {'completed' if result.success else 'did not complete'}. "
            f"Exit code: {result.returncode}"
        )
        if result.success:
            self.logs.appendPlainText(f"\nOutput folder: {result.output_dir}")
            open_folder = QMessageBox.question(
                self, "Package complete",
                f"Package output is in:\n{result.output_dir}\n\nOpen this folder?",
            )
            if open_folder == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.output_dir)))
        else:
            self.logs.appendPlainText("\nPackaging failed or was cancelled.")

    def _packaging_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.plan_label.setText("Packaging failed.")
        self.logs.appendPlainText(f"\nError: {message}")

    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._cancel_event = None
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._cancel()
            event.ignore()
            return
        super().closeEvent(event)
