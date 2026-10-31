# AI index — orientation for coding agents

Read this first when working on this repository.

- Entry: `vibe_code/__main__.py` → `vibe_code/app.py:run()` → `MainWindow`.
- Architecture & request flow: `docs/ARCHITECTURE.md`. Security rules: `docs/SECURITY.md`.
- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest -q`. `tests/conftest.py` disposes Qt widgets after each test — keep references to Qt helper objects (e.g. highlighters) or Qt may segfault at shutdown.
- CI: `.github/workflows/ci.yml` — Ubuntu + Windows, Python 3.11/3.12, plus `package` job (wheel clean-install + PyInstaller bundle smoke tests). Write tests portable to Windows (use `Path`, `write_bytes` for hashed fixtures, `.exe` suffixes).

| Concern | Module |
|---------|--------|
| Symbols / dependency graph / cache | `vibe_code/index/indexer.py`, `extractors.py`, `panel.py` |
| Context ranking, budgets, rules | `vibe_code/context/service.py`, `settings.py` |
| Secret redaction, sensitive paths | `vibe_code/security/redaction.py` |
| Provider HTTP, retries, cancel | `vibe_code/providers/openai_compatible.py`, `base.py` |
| Agent loop / tools | `vibe_code/agent/service.py`, `vibe_code/tools/` |
| Continue / Full Do runner, checkpoints | `vibe_code/agent/autonomy.py` |
| Background jobs, Runs tab | `vibe_code/agent/background.py`, `runs_panel.py` |
| Change snapshots / rollback | `vibe_code/changes/manager.py` |
| Preview adapters, validation | `vibe_code/runtime/` |
| Packaging user projects | `vibe_code/packaging/` ; packaging the IDE: `packaging/build_desktop.py` |

Invariants: all workspace state under `.vibe-code/` written atomically and symlink-checked;
processes use argument arrays with `shell=False`; never mark unvalidated work as passed;
never install dependencies automatically.
