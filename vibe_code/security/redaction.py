"""Secret detection used before any text leaves the machine or reaches a log."""
from __future__ import annotations

import re
from pathlib import PurePath

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/\-]{16,}=*"),
)
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b[\w.\-]*(?:api[_\-]?key|secret|token|passw(?:or)?d|pwd|private[_\-]?key|access[_\-]?key|client[_\-]?secret)[\w.\-]*\b
     ["']?\s*[:=]\s*)
    (["']?)([^\s"',;]{8,})(\2)
    """
)
_BARE_SECRET = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_\-+/=]{12,}$")
_PLACEHOLDERS = {"changeme", "placeholder", "your_api_key", "xxxxxxxx", "redacted", "<secret>", "example"}

SENSITIVE_NAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.development", ".netrc", ".npmrc", ".pypirc",
    "secrets", "secrets.json", "secrets.yaml", "secrets.yml",
    "credentials", "credentials.json", "credentials.yaml", "credentials.yml",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".kdbx"})
_SENSITIVE_MARKERS = ("secret", "credential", "password", "private_key", "api_key", "access_token")
_SENSITIVE_DIRS = frozenset({"secrets", "credentials", "private_keys", ".ssh", ".aws", ".gnupg"})


def is_sensitive_path(relative: PurePath) -> bool:
    name = relative.name.lower()
    return (
        name in SENSITIVE_NAMES
        or name.startswith(".env")
        or relative.suffix.lower() in SENSITIVE_SUFFIXES
        or any(marker in name for marker in _SENSITIVE_MARKERS)
        or any(part.lower() in _SENSITIVE_DIRS for part in relative.parts[:-1])
    )


def redact_secrets(text: str, extra: tuple[str, ...] = ()) -> tuple[str, int]:
    """Return ``(redacted_text, replacements)``. ``extra`` lists literal secrets to mask."""
    count = 0
    for literal in extra:
        if literal and len(literal) >= 6 and literal in text:
            count += text.count(literal)
            text = text.replace(literal, REDACTED)
    for pattern in _PATTERNS:
        text, replaced = pattern.subn(
            lambda m: f"{m.group(1)} {REDACTED}" if m.re.groups else REDACTED, text
        )
        count += replaced

    def assignment(match: re.Match[str]) -> str:
        nonlocal count
        value = match.group(3)
        if value.lower() in _PLACEHOLDERS or value == REDACTED or value.isdigit():
            return match.group(0)
        if not match.group(2) and not _BARE_SECRET.match(value):
            return match.group(0)
        count += 1
        return f"{match.group(1)}{match.group(2)}{REDACTED}{match.group(4)}"

    text = _ASSIGNMENT.sub(assignment, text)
    return text, count
