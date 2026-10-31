"""Lightweight, dependency-free symbol extractors for non-Python languages.

These are line-oriented heuristics, not full parsers. Each extractor returns
``(symbols, imports)`` where symbols are ``(name, kind, line, end_line, parent)``
tuples. Import strings are raw and resolved later by the indexer:

* Rust: ``mod:<name>`` and ``use:<path>``
* C/C++: the include target with its delimiters, e.g. ``"util.h"`` or ``<stdio.h>``
* Go: the import path
"""
from __future__ import annotations

import re

SymbolTuple = tuple[str, str, int, "int | None", "str | None"]

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"')

_RUST_ITEM = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:async|const|unsafe|extern(?:\s+\"[^\"]*\")?)\s+)*"
    r"(fn|struct|enum|trait|type|mod|macro_rules!)\s*([A-Za-z_][A-Za-z0-9_]*)"
)
_RUST_IMPL = re.compile(
    r"^\s*(?:unsafe\s+)?impl(?:\s*<[^{]*?>)?\s+(?:([A-Za-z_][\w:]*)(?:<[^{]*?>)?\s+for\s+)?([A-Za-z_][\w:]*)"
)
_RUST_USE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+([^;]+);")
_RUST_KIND = {"fn": "function", "struct": "struct", "enum": "enum", "trait": "trait",
              "type": "type", "mod": "module", "macro_rules!": "macro"}

_C_INCLUDE = re.compile(r'^\s*#\s*include\s*([<"][^>"]+[>"])')
_C_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_C_TYPE = re.compile(r"^\s*(?:typedef\s+)?(?:template\s*<[^>]*>\s*)?(class|struct|enum(?:\s+class)?|union|namespace)\s+([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^{;]*)?\{?\s*$")
_C_FUNC = re.compile(
    r"^\s*(?:template\s*<[^>]*>\s*)?(?:[A-Za-z_][\w:<>,\s\*&]*?[\s\*&]+)?"
    r"((?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*\([^;]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?:->\s*[\w:<>]+\s*)?\{?\s*$"
)
_C_KEYWORDS = frozenset({"if", "for", "while", "switch", "return", "sizeof", "catch", "else", "do", "case"})

_GO_FUNC = re.compile(r"^func\s+(?:\(\s*\w*\s*\*?\s*([A-Za-z_]\w*)[^)]*\)\s*)?([A-Za-z_]\w*)")
_GO_TYPE = re.compile(r"^type\s+([A-Za-z_]\w*)\s+(struct|interface)?")
_GO_IMPORT_ONE = re.compile(r'^import\s+(?:[\w.]+\s+)?"([^"]+)"')
_GO_IMPORT_ITEM = re.compile(r'^\s*(?:[\w.]+\s+)?"([^"]+)"')


def _strip_comments(text: str) -> list[str]:
    def blank(match: re.Match) -> str:
        return "\n" * match.group(0).count("\n")

    text = _BLOCK_COMMENT.sub(blank, text)
    lines = []
    for line in text.splitlines():
        code = _STRING.sub('""', line)
        cut = code.find("//")
        lines.append(line[:cut] if cut >= 0 else line)
    return lines


def _block_end(lines: list[str], start: int) -> int | None:
    depth = 0
    opened = False
    for index in range(start, len(lines)):
        code = _STRING.sub('""', lines[index])
        for char in code:
            if char == "{":
                depth += 1
                opened = True
            elif char == "}":
                depth -= 1
                if opened and depth <= 0:
                    return index + 1
        if not opened and code.strip().endswith(";"):
            return None
        if not opened and index - start > 3:
            return None
    return None


def extract_rust(text: str) -> tuple[list[SymbolTuple], list[str]]:
    lines = _strip_comments(text)
    symbols: list[SymbolTuple] = []
    imports: list[str] = []
    impl_stack: list[tuple[str, int]] = []
    for number, line in enumerate(lines, 1):
        while impl_stack and number > impl_stack[-1][1]:
            impl_stack.pop()
        use = _RUST_USE.match(line)
        if use:
            imports.append("use:" + re.sub(r"\s+", "", use.group(1)))
            continue
        impl = _RUST_IMPL.match(line)
        if impl:
            target = impl.group(2).split("::")[-1]
            end = _block_end(lines, number - 1)
            if end is not None:
                impl_stack.append((target, end))
            continue
        item = _RUST_ITEM.match(line)
        if not item:
            continue
        keyword, name = item.group(1), item.group(2)
        if keyword == "mod" and line.rstrip().endswith(";"):
            imports.append(f"mod:{name}")
        parent = impl_stack[-1][0] if impl_stack else None
        kind = "method" if keyword == "fn" and parent else _RUST_KIND[keyword]
        symbols.append((name, kind, number, _block_end(lines, number - 1), parent))
    return symbols, imports


def extract_c_family(text: str) -> tuple[list[SymbolTuple], list[str]]:
    lines = _strip_comments(text)
    symbols: list[SymbolTuple] = []
    imports: list[str] = []
    scopes: list[tuple[str, int]] = []
    for number, line in enumerate(lines, 1):
        while scopes and number > scopes[-1][1]:
            scopes.pop()
        include = _C_INCLUDE.match(line)
        if include:
            imports.append(include.group(1))
            continue
        define = _C_DEFINE.match(line)
        if define:
            symbols.append((define.group(1), "macro", number, None, None))
            continue
        if line.lstrip().startswith("#"):
            continue
        parent = scopes[-1][0] if scopes else None
        type_match = _C_TYPE.match(line)
        if type_match:
            keyword = type_match.group(1).split()[0]
            name = type_match.group(2)
            end = _block_end(lines, number - 1)
            symbols.append((name, keyword, number, end, parent))
            if end is not None and keyword in {"class", "struct", "namespace"}:
                scopes.append((name, end))
            continue
        func = _C_FUNC.match(line)
        if func:
            name = func.group(1)
            short = name.split("::")[-1]
            if short in _C_KEYWORDS or line.lstrip().startswith(("return", "else", "}")):
                continue
            end = _block_end(lines, number - 1)
            if end is None:
                continue
            owner = name.rsplit("::", 1)[0] if "::" in name else parent
            kind = "method" if owner and owner != parent or (parent and not _is_namespace(symbols, parent)) else "function"
            symbols.append((short, kind, number, end, owner))
    return symbols, imports


def _is_namespace(symbols: list[SymbolTuple], name: str) -> bool:
    return any(s[0] == name and s[1] == "namespace" for s in symbols)


def extract_go(text: str) -> tuple[list[SymbolTuple], list[str]]:
    lines = _strip_comments(text)
    symbols: list[SymbolTuple] = []
    imports: list[str] = []
    in_import_block = False
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if in_import_block:
            if stripped.startswith(")"):
                in_import_block = False
                continue
            item = _GO_IMPORT_ITEM.match(line)
            if item:
                imports.append(item.group(1))
            continue
        if stripped.startswith("import ("):
            in_import_block = True
            continue
        single = _GO_IMPORT_ONE.match(stripped)
        if single:
            imports.append(single.group(1))
            continue
        func = _GO_FUNC.match(line)
        if func:
            receiver, name = func.group(1), func.group(2)
            kind = "method" if receiver else "function"
            symbols.append((name, kind, number, _block_end(lines, number - 1), receiver))
            continue
        type_match = _GO_TYPE.match(line)
        if type_match:
            kind = type_match.group(2) or "type"
            symbols.append((type_match.group(1), kind, number, _block_end(lines, number - 1), None))
    return symbols, imports
