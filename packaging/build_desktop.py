"""Build a standalone desktop bundle of the IDE with PyInstaller (Linux or Windows).

PyInstaller is NOT a runtime dependency; install it explicitly first:
    python -m pip install -e ".[package]"
    python packaging/build_desktop.py            # -> dist/vibe-code/ (+ .tar.gz / .zip)
    dist/vibe-code/vibe-code --smoke-test        # verify the frozen app starts
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "vibe-code"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--no-archive", action="store_true", help="skip the .tar.gz/.zip archive")
    args = parser.parse_args(argv)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print('PyInstaller is not installed. Run: python -m pip install -e ".[package]"', file=sys.stderr)
        return 2

    sep = os.pathsep
    package = ROOT / "vibe_code"
    work = ROOT / "build" / "pyinstaller"
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        "--distpath", str(args.dist),
        "--workpath", str(work),
        "--specpath", str(work),
        "--add-data", f"{package / 'skills' / 'builtin'}{sep}vibe_code/skills/builtin",
        "--add-data", f"{package / 'templates' / 'builtin'}{sep}vibe_code/templates/builtin",
        str(ROOT / "packaging" / "entry.py"),
    ]
    print(" ".join(command))
    subprocess.run(command, check=True, cwd=ROOT)

    bundle = args.dist / NAME
    if not args.no_archive:
        kind = "zip" if os.name == "nt" else "gztar"
        platform_tag = "windows" if os.name == "nt" else "linux"
        archive = shutil.make_archive(str(args.dist / f"{NAME}-{platform_tag}"), kind, args.dist, NAME)
        print(f"archive: {archive}")
    print(f"bundle: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
