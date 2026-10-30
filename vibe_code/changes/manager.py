from __future__ import annotations

import hashlib
import json
import os
import tempfile
import stat
import difflib
import uuid
from dataclasses import dataclass
from pathlib import Path

from vibe_code.tools.filesystem import WorkspaceFS


@dataclass(frozen=True)
class ChangeRecord:
    path: str
    existed_before: bool
    before_sha256: str | None
    after_sha256: str
    backup_path: str | None


@dataclass(frozen=True)
class ChangeSet:
    id: str
    changes: tuple[ChangeRecord, ...]


class ChangeManager:
    """Persist small, workspace-scoped write snapshots for safe rollback."""

    STATE_DIR = ".vibe-code/changes"

    def __init__(self, filesystem: WorkspaceFS) -> None:
        self.filesystem = filesystem
        self.state_root = self.filesystem.resolve(self.STATE_DIR)
        self.manifest_path = self.state_root / "manifest.json"
        self.state_root.mkdir(parents=True, exist_ok=True)

    def write_text(
        self,
        relative_path: str,
        content: str,
        *,
        expected_sha256: str | None = None,
    ) -> ChangeRecord:
        normalized = Path(relative_path).as_posix()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized == ".vibe-code/changes" or normalized.startswith(".vibe-code/changes/"):
            raise PermissionError("Change state is managed internally")
        path = self.filesystem.resolve(relative_path)
        before = path.read_bytes() if path.exists() else None
        before_hash = self._sha256(before) if before is not None else None
        if expected_sha256 is not None and before_hash != expected_sha256:
            raise RuntimeError(f"Cannot apply reviewed edit: {normalized} changed after the AI preview")

        self._atomic_write(path, content.encode("utf-8"))
        after = path.read_bytes()
        record = ChangeRecord(
            path=self._relative(path),
            existed_before=before is not None,
            before_sha256=before_hash,
            after_sha256=self._sha256(after),
            backup_path=None,
        )

        change_id = uuid.uuid4().hex
        backup_path = self.state_root / change_id / "before"
        if before is not None:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(backup_path, before)
            record = ChangeRecord(
                path=record.path,
                existed_before=True,
                before_sha256=record.before_sha256,
                after_sha256=record.after_sha256,
                backup_path=self._relative_state(backup_path),
            )

        change_set = ChangeSet(change_id, (record,))
        self._save(change_set)
        return record

    def write_many(
        self,
        replacements: dict[str, tuple[str, str]],
    ) -> ChangeSet:
        """Apply a reviewed multi-file edit as one rollback set after full preflight.

        Each value is (new UTF-8 text, expected original SHA-256). Writes are
        individually atomic; if a later write or manifest save fails, earlier
        writes are restored best-effort before the error is propagated.
        """
        if not replacements:
            raise ValueError("No project changes to apply")
        if len(replacements) > 10:
            raise ValueError("A project edit is limited to 10 files")

        prepared = []
        seen: set[str] = set()
        total_bytes = 0
        for relative_path, (content, expected_sha256) in replacements.items():
            normalized = Path(relative_path).as_posix()
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized in seen:
                raise ValueError(f"Duplicate project edit target: {normalized}")
            seen.add(normalized)
            relative = Path(normalized)
            if relative.is_absolute() or ".." in relative.parts or "\\" in normalized or ":" in normalized:
                raise PermissionError(f"Invalid workspace-relative edit path: {normalized}")
            if normalized == ".vibe-code" or normalized.startswith(".vibe-code/"):
                raise PermissionError("IDE state files cannot be edited by project AI")
            if not isinstance(content, str):
                raise TypeError("Project edit content must be text")
            encoded = content.encode("utf-8")
            total_bytes += len(encoded)
            if len(encoded) > 2 * 1024 * 1024 or total_bytes > 4 * 1024 * 1024:
                raise ValueError("Project edit exceeds the file or total size limit")
            lexical = self.filesystem.root / normalized
            cursor = lexical
            while cursor != self.filesystem.root:
                if cursor.is_symlink():
                    raise PermissionError(f"Symlink targets cannot be edited: {normalized}")
                cursor = cursor.parent
            path = self.filesystem.resolve(normalized)
            if not path.exists() or not path.is_file():
                raise ValueError(f"Project edit target is not an existing regular file: {normalized}")
            original = path.read_bytes()
            if len(original) > 2 * 1024 * 1024:
                raise ValueError(f"Target exceeds the 2 MiB file limit: {normalized}")
            if b"\x00" in original:
                raise ValueError(f"Binary files cannot be edited: {normalized}")
            before_hash = self._sha256(original)
            if before_hash != expected_sha256:
                raise RuntimeError(f"Cannot apply reviewed edit: {normalized} changed after preview")
            try:
                original.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Target is not UTF-8 text: {normalized}") from exc
            prepared.append((normalized, path, original, encoded, before_hash))

        change_id = uuid.uuid4().hex
        records: list[ChangeRecord] = []
        written: list[tuple[Path, bytes]] = []
        try:
            for normalized, path, original, encoded, before_hash in prepared:
                backup_path = self.state_root / change_id / normalized
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_write(backup_path, original)
                self._atomic_write(path, encoded)
                written.append((path, original))
                after = path.read_bytes()
                records.append(ChangeRecord(
                    path=normalized,
                    existed_before=True,
                    before_sha256=before_hash,
                    after_sha256=self._sha256(after),
                    backup_path=self._relative_state(backup_path),
                ))
            change_set = ChangeSet(change_id, tuple(records))
            self._save(change_set)
            return change_set
        except Exception:
            for path, original in reversed(written):
                try:
                    self._atomic_write(path, original)
                except OSError:
                    pass
            raise

    def list_changes(self) -> tuple[ChangeSet, ...]:
        data = self._read_manifest()
        result: list[ChangeSet] = []
        for change_id, payload in data.items():
            if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
                continue
            records = tuple(
                ChangeRecord(
                    path=item["path"],
                    existed_before=bool(item["existed_before"]),
                    before_sha256=item.get("before_sha256"),
                    after_sha256=item["after_sha256"],
                    backup_path=item.get("backup_path"),
                )
                for item in payload["changes"]
                if isinstance(item, dict)
            )
            result.append(ChangeSet(change_id, records))
        return tuple(reversed(result))

    def get_change(self, change_id: str) -> ChangeSet:
        data = self._load(change_id)
        records = tuple(
            ChangeRecord(
                path=item["path"],
                existed_before=bool(item["existed_before"]),
                before_sha256=item.get("before_sha256"),
                after_sha256=item["after_sha256"],
                backup_path=item.get("backup_path"),
            )
            for item in data["changes"]
        )
        return ChangeSet(change_id, records)

    def diff(self, change_id: str) -> str:
        change_set = self.get_change(change_id)
        chunks: list[str] = []
        for record in change_set.changes:
            before = ""
            if record.existed_before and record.backup_path:
                before = self._state_resolve(record.backup_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            path = self._resolve_change_target(record.path)
            after = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            chunks.extend(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{record.path}",
                    tofile=f"b/{record.path}",
                )
            )
        return "".join(chunks) or "(no textual diff)"

    def rollback_many(self, change_ids: tuple[str, ...] | list[str]) -> tuple[ChangeSet, ...]:
        """Preflight and rollback several change sets without partial application."""
        ids = tuple(dict.fromkeys(change_ids))
        if not ids:
            return ()
        change_sets = tuple(self.get_change(change_id) for change_id in ids)
        records = [record for change_set in change_sets for record in change_set.changes]
        prepared = self._preflight_rollback(records)
        self._restore_preflighted(prepared)
        return change_sets

    def rollback(self, change_id: str) -> ChangeSet:
        change_set = self.get_change(change_id)
        prepared = self._preflight_rollback(list(change_set.changes))
        self._restore_preflighted(prepared)
        return change_set

    def _preflight_rollback(self, records: list[ChangeRecord]):
        prepared = []
        for record in records:
            path = self._resolve_change_target(record.path)
            current = path.read_bytes() if path.exists() else None
            current_hash = self._sha256(current) if current is not None else None
            if current_hash != record.after_sha256:
                raise RuntimeError(
                    f"Cannot rollback {record.path}: file changed after the recorded write"
                )
            backup = None
            if record.existed_before:
                if not record.backup_path:
                    raise RuntimeError(f"Missing backup for {record.path}")
                backup_path = self._state_resolve(record.backup_path)
                if not backup_path.is_file():
                    raise RuntimeError(f"Missing backup for {record.path}")
                backup = backup_path.read_bytes()
                if self._sha256(backup) != record.before_sha256:
                    raise RuntimeError(f"Backup verification failed for {record.path}")
            prepared.append((record, path, current, backup))
        return prepared

    def _restore_preflighted(self, prepared) -> None:
        restored = []
        try:
            for record, path, current, backup in prepared:
                if record.existed_before:
                    self._atomic_write(path, backup)
                elif path.exists():
                    path.unlink()
                restored.append((path, current))
        except Exception:
            # Best-effort recovery to the state immediately before rollback.
            for path, current in reversed(restored):
                try:
                    if current is None:
                        if path.exists():
                            path.unlink()
                    else:
                        self._atomic_write(path, current)
                except OSError:
                    pass
            raise

    def _save(self, change_set: ChangeSet) -> None:
        payload = {
            "id": change_set.id,
            "changes": [
                {
                    "path": item.path,
                    "existed_before": item.existed_before,
                    "before_sha256": item.before_sha256,
                    "after_sha256": item.after_sha256,
                    "backup_path": item.backup_path,
                }
                for item in change_set.changes
            ],
        }
        data = json.dumps(
            {**self._read_manifest(), change_set.id: payload},
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        self._atomic_write(self.manifest_path, data)

    def _load(self, change_id: str) -> dict[str, object]:
        data = self._read_manifest()
        try:
            payload = data[change_id]
        except KeyError as exc:
            raise KeyError(f"Unknown change set: {change_id}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
            raise RuntimeError(f"Invalid change set: {change_id}")
        return payload

    def _read_manifest(self) -> dict[str, object]:
        if not self.manifest_path.exists():
            return {}
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("Invalid change manifest")
        return data

    def _resolve_change_target(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in relative_path or ":" in relative_path:
            raise PermissionError("Invalid recorded workspace path")
        lexical = self.filesystem.root / relative
        cursor = lexical
        while cursor != self.filesystem.root:
            if cursor.is_symlink():
                raise PermissionError("Cannot operate on a symlinked change target")
            cursor = cursor.parent
        return self.filesystem.resolve(relative_path)

    def _state_resolve(self, relative_path: str) -> Path:
        candidate = (self.filesystem.root / relative_path).resolve()
        if candidate != self.state_root and self.state_root not in candidate.parents:
            raise PermissionError("Invalid change backup path")
        return candidate

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.filesystem.root).as_posix()

    def _relative_state(self, path: Path) -> str:
        return path.relative_to(self.filesystem.root).as_posix()

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            original_mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            original_mode = None
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            if original_mode is not None:
                os.chmod(temp_name, original_mode)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
