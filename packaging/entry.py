"""PyInstaller entry point (absolute import so the frozen bootloader can resolve the package)."""
from vibe_code.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
