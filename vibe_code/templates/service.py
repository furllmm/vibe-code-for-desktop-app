from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


_BUILTIN_ROOT = Path(__file__).resolve().parent / "builtin"


class TemplateError(ValueError):
    """A template is invalid or cannot be safely applied."""


@dataclass(frozen=True)
class TemplateFile:
    path: str
    content: str
    exists: bool


@dataclass(frozen=True)
class TemplatePlan:
    template_id: str
    name: str
    description: str
    files: tuple[TemplateFile, ...]


class TemplateService:
    """Load packaged templates and apply them only after an explicit caller approval.

    Existing files are skipped by default. Overwrites must be explicitly enabled by
    the caller after showing the plan to the user.
    """

    def __init__(self, template_root: Path | None = None) -> None:
        self.template_root = (template_root or _BUILTIN_ROOT).expanduser().resolve()

    def list_templates(self) -> list[dict[str, str]]:
        if not self.template_root.is_dir():
            return []
        result: list[dict[str, str]] = []
        for manifest_path in sorted(self.template_root.glob("*/template.json")):
            try:
                manifest = self._read_manifest(manifest_path)
            except (OSError, UnicodeError, json.JSONDecodeError, TemplateError):
                continue
            result.append({
                "id": manifest["id"],
                "name": manifest["name"],
                "description": manifest["description"],
            })
        return result

    def plan(self, template_id: str, workspace: Path) -> TemplatePlan:
        template_dir = self._template_dir(template_id)
        manifest = self._read_manifest(template_dir / "template.json")
        root = workspace.expanduser().resolve()
        mapping = manifest["files"]
        planned: list[TemplateFile] = []
        for target_name, source_name in mapping.items():
            target_rel = self._safe_relative_path(target_name, "target")
            source_rel = self._safe_relative_path(source_name, "source")
            source_candidate = template_dir / "files" / Path(*source_rel.parts)
            source_root = (template_dir / "files").resolve()
            current_source = template_dir / "files"
            for part in source_rel.parts:
                current_source = current_source / part
                if current_source.is_symlink():
                    raise TemplateError(f"Refusing to follow symlink in template source: {source_name}")
            source = source_candidate.resolve()
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise TemplateError(f"Template source escapes its directory: {source_name}") from exc
            if not source.is_file() or source.is_symlink():
                raise TemplateError(f"Template source is not a regular file: {source_name}")
            try:
                content = source.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise TemplateError(f"Could not read template source {source_name}: {exc}") from exc
            destination = self._resolve_destination(root, target_rel, allow_missing=True)
            exists = destination.exists()
            if exists and (destination.is_symlink() or not destination.is_file()):
                raise TemplateError(f"Refusing to replace a non-regular file: {target_name}")
            planned.append(TemplateFile(target_rel.as_posix(), content, exists))
        return TemplatePlan(
            template_id=manifest["id"],
            name=manifest["name"],
            description=manifest["description"],
            files=tuple(planned),
        )

    def apply(
        self,
        template_id: str,
        workspace: Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, list[str]]:
        # Recompute immediately before writing; callers should show a preview first.
        plan = self.plan(template_id, workspace)
        root = workspace.expanduser().resolve()
        create: list[tuple[Path, str, str]] = []
        skipped: list[str] = []
        for item in plan.files:
            relative = self._safe_relative_path(item.path, "target")
            destination = self._resolve_destination(root, relative, allow_missing=True)
            if destination.exists():
                if destination.is_symlink() or not destination.is_file():
                    raise TemplateError(f"Refusing to replace a non-regular file: {item.path}")
                if not overwrite:
                    skipped.append(item.path)
                    continue
            create.append((destination, item.path, item.content))

        # Prepare every file before replacing any destination, so validation and
        # write failures during staging do not leave a partially applied template.
        staged: list[tuple[Path, Path, str]] = []
        try:
            for destination, relative, content in create:
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Re-check parent containment after mkdir, including symlink parents.
                self._resolve_destination(
                    root, self._safe_relative_path(relative, "target"), allow_missing=True
                )
                fd, temp_name = tempfile.mkstemp(
                    prefix=".vibe-template-", dir=destination.parent
                )
                temp_path = Path(temp_name)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    temp_path.unlink(missing_ok=True)
                    raise
                staged.append((temp_path, destination, relative))

            # No overwrite occurs unless the caller explicitly opted in.
            # Re-check destinations immediately before replacement.
            for temp_path, destination, relative in staged:
                self._resolve_destination(
                    root, self._safe_relative_path(relative, "target"), allow_missing=True
                )
                if destination.exists() and not overwrite:
                    raise TemplateError(
                        f"File appeared during template application; retry after review: {relative}"
                    )
            created: list[str] = []
            for temp_path, destination, relative in staged:
                os.replace(temp_path, destination)
                created.append(relative)
        except Exception:
            for temp_path, _, _ in staged:
                temp_path.unlink(missing_ok=True)
            raise
        return {"created": created, "skipped": skipped}

    def _template_dir(self, template_id: str) -> Path:
        if not isinstance(template_id, str) or not template_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in template_id
        ):
            raise TemplateError("Invalid template id")
        directory = (self.template_root / template_id).resolve()
        try:
            directory.relative_to(self.template_root)
        except ValueError as exc:
            raise TemplateError("Template id escapes the template directory") from exc
        if not directory.is_dir():
            raise TemplateError(f"Unknown template: {template_id}")
        return directory

    @staticmethod
    def _safe_relative_path(value: Any, label: str) -> PurePosixPath:
        if not isinstance(value, str) or not value or "\\" in value:
            raise TemplateError(f"Invalid {label} path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise TemplateError(f"Unsafe {label} path: {value}")
        if path.parts and ":" in path.parts[0]:
            raise TemplateError(f"Unsafe {label} path: {value}")
        return path

    @staticmethod
    def _resolve_destination(
        root: Path, relative: PurePosixPath, *, allow_missing: bool = False
    ) -> Path:
        destination = root.joinpath(*relative.parts)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise TemplateError(f"Refusing to follow symlink in destination path: {relative}")
            if current.exists() and not current.is_dir():
                raise TemplateError(f"Destination parent is not a directory: {relative}")
        if destination.is_symlink():
            raise TemplateError(f"Refusing to write through symlink: {relative}")
        try:
            destination.resolve(strict=not allow_missing).relative_to(root)
        except (ValueError, FileNotFoundError) as exc:
            raise TemplateError(f"Destination escapes workspace: {relative}") from exc
        return destination

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TemplateError(f"Could not read template manifest {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise TemplateError("Template manifest must be a JSON object")
        template_id = data.get("id")
        name = data.get("name")
        description = data.get("description", "")
        files = data.get("files")
        if (
            not isinstance(template_id, str)
            or not template_id
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(description, str)
            or not isinstance(files, dict)
            or not files
        ):
            raise TemplateError(f"Invalid template manifest: {path}")
        if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in template_id):
            raise TemplateError(f"Invalid template id in manifest: {path}")
        if path.parent.name != template_id:
            raise TemplateError(f"Template id does not match its directory: {path}")
        for target, source in files.items():
            TemplateService._safe_relative_path(target, "target")
            TemplateService._safe_relative_path(source, "source")
        return {
            "id": template_id,
            "name": name.strip(),
            "description": description.strip(),
            "files": files,
        }
