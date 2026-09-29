from __future__ import annotations

import hashlib
import json
import os
import tempfile
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

    def write_text(self, relative_path: str, content: str) -> ChangeRecord:
        normalized = Path(relative_path).as_posix().lstrip("./")
        if normalized == ".vibe-code/changes" or normalized.startswith(".vibe-code/changes/"):
            raise PermissionError("Change state is managed internally")
        path = self.filesystem.resolve(relative_path)
        before = path.read_bytes() if path.exists() else None
        before_hash = self._sha256(before) if before is not None else None

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

    def rollback(self, change_id: str) -> ChangeSet:
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

        for record in records:
            path = self.filesystem.resolve(record.path)
            current = path.read_bytes() if path.exists() else None
            current_hash = self._sha256(current) if current is not None else None
            if current_hash != record.after_sha256:
                raise RuntimeError(
                    f"Cannot rollback {record.path}: file changed after the recorded write"
                )

            if record.existed_before:
                if not record.backup_path:
                    raise RuntimeError(f"Missing backup for {record.path}")
                backup = self._state_resolve(record.backup_path)
                self._atomic_write(path, backup.read_bytes())
            elif path.exists():
                path.unlink()

        return ChangeSet(change_id, records)

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
        self.manifest_path.write_text(
            json.dumps(
                {**self._read_manifest(), change_set.id: payload},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

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

    def _state_resolve(self, relative_path: str) -> Path:
        candidate = (self.state_root / Path(relative_path).name).resolve()
        if candidate != self.state_root and self.state_root not in candidate.parents:
            raise PermissionError("Invalid change backup path")
        # Stored paths are generated internally; keep nested backup paths supported.
        candidate = (self.filesystem.root / relative_path).resolve()
        if self.filesystem.root not in candidate.parents:
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
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
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
