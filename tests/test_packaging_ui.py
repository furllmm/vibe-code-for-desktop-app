import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vibe_code.packaging.dialog import PackagingDialog


_APP = QApplication.instance() or QApplication([])


def test_packaging_dialog_exposes_supported_backends_and_formats(tmp_path):
    dialog = PackagingDialog(tmp_path)
    try:
        assert dialog.windowTitle() == "Package Project"
        assert dialog.backend.count() == 4
        assert dialog.package_type.count() == 2

        dialog.backend.setCurrentIndex(1)
        assert dialog.package_type.count() == 8
        assert dialog.package_type.itemData(0) == "zip"

        dialog.backend.setCurrentIndex(2)
        assert dialog.package_type.count() == 1
        assert dialog.package_type.itemData(0) == "app-image"
    finally:
        dialog.close()
