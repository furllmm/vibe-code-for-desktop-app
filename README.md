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


## Agent runner

The desktop UI can run a bounded coding-agent loop against any **Chat Completions-compatible** endpoint.

Configure the provider through environment variables:

```bash
export VIBE_CODE_BASE_URL="http://localhost:8000/v1"
export VIBE_CODE_MODEL="your-model"
export VIBE_CODE_API_KEY="optional"
export VIBE_CODE_TIMEOUT="60"
python -m vibe_code
```

Then open a workspace, describe a change, and press **Run Agent**.

The current agent tool allow-list contains:
- `read_file`
- `write_file`

Both are restricted to the selected workspace. Agent execution runs outside the Qt GUI thread so a slow provider request does not block the interface.

The current provider adapter targets the Chat Completions contract; it does not claim compatibility with the separate Responses API.


## Desktop preview

The first preview MVP uses an explicit command and does not invoke a shell:

```bash
export VIBE_CODE_PREVIEW_COMMAND="python -m your_app"
python -m vibe_code
```

The IDE provides **Run Preview** and **Stop Preview**. Preview stdout/stderr is captured and displayed in the chat output, and non-zero exits are reported as crash/error exits.

The preview layer is adapter-based so language-specific detection/build/run behavior can be added without changing the IDE UI. The current generic adapter intentionally performs no automatic build.


### Python/PySide6 preview

If VIBE_CODE_PREVIEW_COMMAND is not set, the desktop shell can automatically detect a Python/PySide6 workspace and infer an entrypoint from main.py, app.py, src/main.py, src/app.py, or project.scripts.preview in pyproject.toml. An explicit entrypoint can be supplied with VIBE_CODE_PYTHON_ENTRYPOINT. The adapter keeps the entrypoint inside the workspace and runs it with the current Python interpreter.
