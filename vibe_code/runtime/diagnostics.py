from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

MAX_DIAGNOSTIC_CHARS = 64 * 1024
MAX_LOCATIONS = 100
_ALLOWED_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".kt", ".rs",
    ".go", ".cs", ".fs", ".vb", ".swift", ".m", ".mm", ".qml",
}
_SENSITIVE_PARTS = {".env", "secrets", "credentials", "private_keys", "id_rsa", "id_ed25519"}
_PATTERNS = (
    re.compile(r'File ["\'](?P<path>[^"\']+)["\'], line (?P<line>\d+)'),
    re.compile(r'(?m)^\s*(?:-->\s*)?(?P<path>(?:[A-Za-z]:[\\/])?[^\s<>:"|]+\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|c|cc|cpp|h|hpp|java|kt|rs|go|cs|fs|vb|swift|m|mm|qml)):(?P<line>\d+)(?::\d+)?(?::|\s|$)'),
    re.compile(r'\((?P<path>[^()]+\.(?:java|kt)):(?P<line>\d+)\)'),
    re.compile(r'\bin\s+(?P<path>[^\s]+\.(?:cs|fs|vb)):line\s+(?P<line>\d+)'),
)
_SECRET_PATTERNS = (
    re.compile(r'(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*)([^\s,;]+)'),
    re.compile(r'(?i)(\bAuthorization\s*:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+'),
)


@dataclass(frozen=True)
class DiagnosticLocation:
    path: str
    line: int
    source_excerpt: str


def redact_diagnostics(text: str) -> str:
    """Remove common inline credentials before diagnostic text reaches a provider."""
    value = text[-MAX_DIAGNOSTIC_CHARS:]
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(r"\1[REDACTED]", value)
    return value


def parse_diagnostics(text: str, workspace: Path) -> tuple[DiagnosticLocation, ...]:
    """Extract only existing, in-workspace source locations from untrusted logs."""
    if not isinstance(text, str):
        raise TypeError("diagnostics must be text")
    root = workspace.expanduser().resolve()
    found: dict[tuple[str, int], DiagnosticLocation] = {}
    bounded = text[-MAX_DIAGNOSTIC_CHARS:]
    for pattern in _PATTERNS:
        for match in pattern.finditer(bounded):
            raw_path = match.group("path").strip().strip("'\"")
            try:
                candidate = Path(raw_path)
                if not candidate.is_absolute():
                    candidate = root / candidate
                candidate = Path(os.path.abspath(candidate))
                candidate.relative_to(root)
                cursor = candidate
                has_symlink = False
                while cursor != root.parent:
                    if cursor.is_symlink():
                        has_symlink = True
                        break
                    cursor = cursor.parent
                if has_symlink:
                    continue
                resolved = candidate.resolve(strict=True)
                relative = resolved.relative_to(root).as_posix()
                if any(part.lower() in _SENSITIVE_PARTS or part.lower().startswith(".env") for part in Path(relative).parts):
                    continue
                if resolved.suffix.lower() not in _ALLOWED_SUFFIXES or not resolved.is_file():
                    continue
                if resolved.stat().st_size > 2 * 1024 * 1024:
                    continue
                line = int(match.group("line"))
                if line < 1:
                    continue
                lines = resolved.read_text(encoding="utf-8").splitlines()
                if line > len(lines):
                    continue
                start, end = max(0, line - 3), min(len(lines), line + 2)
                excerpt = "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end))
                excerpt = redact_diagnostics(excerpt)
                found.setdefault((relative, line), DiagnosticLocation(relative, line, excerpt[:4000]))
                if len(found) >= MAX_LOCATIONS:
                    return tuple(found.values())
            except (OSError, UnicodeError, ValueError, RuntimeError):
                continue
    return tuple(found.values())
