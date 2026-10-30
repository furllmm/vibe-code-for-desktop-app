from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
from pathlib import Path
import tempfile

from vibe_code.workspace import Workspace


MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024
MAX_SEARCH_FILES = 20_000
MAX_SEARCH_RESULTS = 5_000
MAX_REPLACE_FILES = 100
MAX_REPLACE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SEARCH_TOTAL_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class SearchMatch:
    path: Path
    line: int
    column: int
    text: str


@dataclass(frozen=True)
class ReplacementFile:
    path: Path
    before_hash: str
    before: bytes
    after: bytes
    matches: int


@dataclass(frozen=True)
class ReplacementPlan:
    files: tuple[ReplacementFile, ...]

    @property
    def match_count(self) -> int:
        return sum(item.matches for item in self.files)


def _iter_text_files(workspace: Workspace):
    ignored_dirs = {
        ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
        "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "dist", "build",
    }
    count = 0
    for current, dirs, names in os.walk(workspace.root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(
            name for name in dirs
            if name not in ignored_dirs
            and not (base / name).is_symlink()
        )
        for name in sorted(names):
            candidate = base / name
            if candidate.is_symlink():
                continue
            try:
                resolved = workspace.resolve(candidate)
                if not resolved.is_file() or resolved.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
            except (OSError, ValueError):
                continue
            count += 1
            if count > MAX_SEARCH_FILES:
                raise ValueError(f"Workspace contains more than {MAX_SEARCH_FILES} searchable files")
            yield resolved


def _read_text(path: Path) -> tuple[bytes, str] | None:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_SEARCH_FILE_BYTES or b"\x00" in raw:
            return None
        return raw, raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def search_workspace(
    workspace: Workspace,
    query: str,
    *,
    case_sensitive: bool = False,
    max_results: int = MAX_SEARCH_RESULTS,
) -> list[SearchMatch]:
    if not query:
        raise ValueError("Search query must not be empty")
    if max_results < 1 or max_results > MAX_SEARCH_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_SEARCH_RESULTS}")
    results: list[SearchMatch] = []
    scanned_bytes = 0
    for path in _iter_text_files(workspace):
        loaded = _read_text(path)
        if loaded is None:
            continue
        raw, content = loaded
        scanned_bytes += len(raw)
        if scanned_bytes > MAX_SEARCH_TOTAL_BYTES:
            raise ValueError(
                f"Workspace search exceeded the {MAX_SEARCH_TOTAL_BYTES // (1024 * 1024)} MiB scan limit"
            )
        expression = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
        for line_number, line in enumerate(content.splitlines(), 1):
            for match in expression.finditer(line):
                results.append(SearchMatch(
                    path=path,
                    line=line_number,
                    column=match.start() + 1,
                    text=line[:500],
                ))
                if len(results) >= max_results:
                    return results
    return results


def build_replacement_plan(
    workspace: Workspace,
    query: str,
    replacement: str,
    *,
    case_sensitive: bool = False,
) -> ReplacementPlan:
    if not query:
        raise ValueError("Search query must not be empty")
    planned: list[ReplacementFile] = []
    planned_bytes = 0
    scanned_bytes = 0
    pattern = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    for path in _iter_text_files(workspace):
        loaded = _read_text(path)
        if loaded is None:
            continue
        raw, content = loaded
        scanned_bytes += len(raw)
        if scanned_bytes > MAX_SEARCH_TOTAL_BYTES:
            raise ValueError(
                f"Replacement preview exceeded the {MAX_SEARCH_TOTAL_BYTES // (1024 * 1024)} MiB scan limit"
            )
        updated, count = pattern.subn(lambda _match: replacement, content)
        if count:
            planned_bytes += len(raw)
            if planned_bytes > MAX_REPLACE_TOTAL_BYTES:
                raise ValueError(
                    f"Replacement preview exceeds the {MAX_REPLACE_TOTAL_BYTES // (1024 * 1024)} MiB total file limit"
                )
            planned.append(ReplacementFile(
                path=path,
                before_hash=hashlib.sha256(raw).hexdigest(),
                before=raw,
                after=updated.encode("utf-8"),
                matches=count,
            ))
            if len(planned) > MAX_REPLACE_FILES:
                raise ValueError(
                    f"Replacement affects more than {MAX_REPLACE_FILES} files; "
                    "narrow the search before replacing"
                )
    return ReplacementPlan(tuple(planned))


def _atomic_write(path: Path, payload: bytes, mode: int) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".vibe-code-replace-", dir=path.parent)
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


def apply_replacement_plan(
    workspace: Workspace,
    plan: ReplacementPlan,
) -> int:
    if not plan.files:
        return 0

    # Validate every target before writing any file.
    modes: dict[Path, int] = {}
    for item in plan.files:
        path = workspace.resolve(item.path)
        if path != item.path or not path.is_file() or path.is_symlink():
            raise ValueError(f"Replacement target is no longer a regular workspace file: {item.path}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.before_hash:
            raise ValueError(f"File changed after preview; no replacements applied: {path}")
        modes[path] = path.stat().st_mode & 0o777

    applied: list[ReplacementFile] = []
    try:
        for item in plan.files:
            path = workspace.resolve(item.path)
            _atomic_write(path, item.after, modes[path])
            applied.append(item)
    except Exception:
        # Best-effort rollback of already committed files if a later write fails.
        rollback_errors: list[str] = []
        for item in reversed(applied):
            try:
                path = workspace.resolve(item.path)
                _atomic_write(path, item.before, modes[path])
            except Exception as rollback_error:
                rollback_errors.append(f"{item.path}: {rollback_error}")
        if rollback_errors:
            raise RuntimeError(
                "Replacement failed and rollback was incomplete: " + "; ".join(rollback_errors)
            )
        raise
    return plan.match_count
