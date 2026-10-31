# Changelog

All notable changes are listed here. Format: [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Canonical integration branch combining the phase 1–9 (templates, approvals, Enhance/Continue, skills) and phase 10–18 (preview adapters, packaging, AI edit/chat, validation, debugger) chains.
- Structural Project Indexer: Python AST, Rust, C/C++ and Go symbols/imports, dependency graph, reverse dependents, git change history, incremental cache with corruption recovery, generated-file detection, bounded scanning; **Index** tab.
- Context engine: graph/history-aware ranking, token budgets, `.vibe-code/context.json`, `.vibeignore`, project rules (`.vibe-code/rules.md` / `AGENTS.md`), sensitive-path exclusion and secret redaction.
- Provider: retries with backoff and `Retry-After`, cancellation, token usage, model listing, **Test Provider**, sanitised `ProviderError`s, outgoing secret redaction.
- Continue / Full Do autonomous runner with iteration/token/time budgets, per-task retries, validation, loop detection, approval guard for destructive tools, atomic checkpoints and resume.
- Background execution (`BackgroundTaskManager`) and **Runs** tab: run in background, live progress/log, cancel, resume, duplicate prevention, interrupted-run recovery.
- `--version` and `--smoke-test` CLI flags; PyInstaller build script (`packaging/build_desktop.py`, extra `[package]`); CI `package` job with clean-install, reinstall and frozen-bundle smoke tests on Linux and Windows.
- Docs: architecture, security boundaries, provider configuration.

### Fixed
- App crashed on start (`QSplitter.setOrientation(int)`).
- Templates failed for new files; skill relevance false positives.
- Intermittent Qt segfault at interpreter shutdown (unreferenced syntax highlighter, undisposed widgets in tests).
- Windows test failures (paths, `.exe` suffix, newline-sensitive hashes).
- Run checkpoints written by other app versions are no longer rejected as corrupted.

## [0.1.0]
- Initial foundation: PySide6 shell, workspace model, context core, provider interface, workspace-scoped tools.
