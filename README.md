# Vibe Code for Desktop Apps

AI-first local desktop development environment for building, running, debugging, and packaging desktop applications from natural-language instructions.

## Vision

Describe a desktop app. Let the agent inspect the project, write code, run it, diagnose failures, and iterate.

The architecture is **context-engineering-first**: retrieve only the project knowledge needed for each task instead of sending the whole repository on every turn.

## Phase 1 foundation

- PySide6 desktop shell
- Workspace model
- Context engineering core
- Provider-neutral AI interface
- Workspace-scoped filesystem tool
- SQLite-ready storage boundary
- Clean package boundaries for future agent/runtime work

## Architecture

```
vibe_code/
  app.py
  context/      project discovery, scoring, context packs
  providers/    AI provider interfaces
  tools/        explicit workspace-scoped tools
  storage/      persistent local state
  workspace/    project lifecycle
```

## Principles

1. Context is assembled on demand.
2. Agent capabilities have explicit boundaries.
3. File changes remain auditable and diffable.
4. Long-running commands will be cancellable.
5. Provider-specific code stays behind interfaces.
6. Local-first is a design goal.

## Development

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m vibe_code
pytest
```

Status: early foundation / active development.
