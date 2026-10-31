"""Post-install check: the installed package imports, ships its data files and starts.

Run with the *installed* interpreter, outside the source tree:
    QT_QPA_PLATFORM=offscreen python scripts/smoke_install.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import importlib

    import vibe_code

    for module in ("vibe_code.app", "vibe_code.skills.service", "vibe_code.templates.service"):
        importlib.import_module(module)

    package = Path(vibe_code.__file__).resolve().parent
    if (package.parent / "pyproject.toml").exists():
        print(f"error: imported from the source tree ({package}); run outside the checkout")
        return 1
    skills = list((package / "skills" / "builtin").rglob("SKILL.md"))
    templates = list((package / "templates" / "builtin").rglob("template.json"))
    if not skills or not templates:
        print(f"error: package data missing (skills={len(skills)}, templates={len(templates)})")
        return 1
    for args in (["--version"], ["--smoke-test"]):
        result = subprocess.run([sys.executable, "-m", "vibe_code", *args], timeout=120)
        if result.returncode != 0:
            print(f"error: vibe_code {args[0]} exited with {result.returncode}")
            return 1
    print(f"ok: {package} ({len(skills)} skills, {len(templates)} templates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
