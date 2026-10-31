from __future__ import annotations

import json

import pytest

from vibe_code.templates.service import TemplateError, TemplateService


def test_builtin_template_is_listed_and_previewed(tmp_path):
    service = TemplateService()
    templates = service.list_templates()
    assert any(item["id"] == "python-pyside6" for item in templates)

    plan = service.plan("python-pyside6", tmp_path)
    assert plan.name == "Python + PySide6"
    assert {item.path for item in plan.files} == {"src/main.py", "pyproject.toml"}
    assert all(not item.exists for item in plan.files)
    assert not (tmp_path / "src" / "main.py").exists()


def test_apply_creates_files_and_skips_existing_by_default(tmp_path):
    service = TemplateService()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("user code\n", encoding="utf-8")

    result = service.apply("python-pyside6", tmp_path)
    assert result["created"] == ["pyproject.toml"]
    assert result["skipped"] == ["src/main.py"]
    assert (tmp_path / "src" / "main.py").read_text(encoding="utf-8") == "user code\n"
    assert (tmp_path / "pyproject.toml").is_file()


def test_overwrite_requires_explicit_opt_in(tmp_path):
    service = TemplateService()
    (tmp_path / "pyproject.toml").write_text("my config", encoding="utf-8")
    service.apply("python-pyside6", tmp_path)
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == "my config"

    result = service.apply("python-pyside6", tmp_path, overwrite=True)
    assert "pyproject.toml" in result["created"]
    assert "[project]" in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_template_id_traversal_is_rejected(tmp_path):
    with pytest.raises(TemplateError, match="Invalid template id"):
        TemplateService().plan("../outside", tmp_path)


def test_manifest_rejects_target_path_traversal(tmp_path):
    root = tmp_path / "templates"
    template = root / "bad"
    (template / "files").mkdir(parents=True)
    (template / "files" / "main.py").write_text("bad", encoding="utf-8")
    (template / "template.json").write_text(
        json.dumps({
            "id": "bad",
            "name": "Bad",
            "description": "bad path",
            "files": {"../outside.txt": "main.py"},
        }),
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="Unsafe target path"):
        TemplateService(root).plan("bad", tmp_path / "workspace")


def test_destination_symlink_is_rejected(tmp_path):
    service = TemplateService()
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").symlink_to(outside, target_is_directory=True)
    with pytest.raises(TemplateError, match="symlink"):
        service.plan("python-pyside6", workspace)
