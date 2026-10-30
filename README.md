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


### Agent preview tools

When a preview adapter is available, the coding agent receives an explicit allow-list of `run_preview`, `get_preview_logs`, and `stop_preview`. The agent is instructed to validate meaningful changes with the preview and inspect diagnostics before finishing. Preview process commands remain owned by the configured adapter rather than being supplied by the model.


### Multi-language preview adapters

Automatic preview detection currently supports:
- Python/PySide6 (runs the detected Python entrypoint)
- C and C++ projects using CMake (builds in `.vibe-code/build/cmake`; resolves a single executable via the CMake file API)
- Java Maven or Gradle projects (builds and launches one JAR with a `Main-Class` manifest)
- Rust/Cargo (builds with `cargo build`, runs the debug binary)
- Go (builds to `.vibe-code/bin/preview`, then runs it)
- .NET single-target `.csproj` projects (builds and launches the output assembly)
- Electron projects with a locally installed Electron runtime
- Node projects declaring a `scripts.start` command

Builds use argument arrays with `shell=False`, a bounded timeout, and captured diagnostics. The IDE does not run package installation or arbitrary packaging scripts automatically. Install project dependencies yourself before previewing. Set `VIBE_CODE_PREVIEW_COMMAND` to override automatic detection.

The current .NET adapter intentionally supports one top-level project and one `TargetFramework`; multi-target and solution-level project selection remain future work.


CMake preview requires CMake and a working C/C++ compiler toolchain. If the CMake project produces multiple executable targets, automatic preview stops and asks for a single preview target rather than guessing. Java preview requires the corresponding system build tool (`mvn` or `gradle`) and a runnable JAR with a `Main-Class` manifest; dependency/classpath assembly is not inferred. Java build scripts can execute project-defined code and may download dependencies, so use preview only with workspaces you trust. Local build products and IDE change state under `.vibe-code/` are ignored by Git.


## Packaging engine (Phase 7)

The packaging core currently exposes explicit, inspectable packaging plans through `vibe_code.packaging.PackagingEngine`:

- **Python / PyInstaller**: one-file or one-folder bundles; requires PyInstaller to be installed in the IDE's Python environment and an explicit workspace-relative entrypoint.
- **C/C++ / CPack**: ZIP, TGZ, DEB, RPM, NSIS, IFW, DragNDrop, or productbuild when the project generated `.vibe-code/build/cmake/CPackConfig.cmake` and the corresponding CPack generator is installed.
- **Java / jpackage**: portable `app-image` output from a runnable JAR with a `Main-Class` manifest; requires a full JDK.

Example (Python):

```python
from pathlib import Path
from vibe_code.packaging import PackageRequest, PackagingEngine

engine = PackagingEngine(Path("/path/to/workspace"))
plan = engine.create_plan(PackageRequest(
    backend="pyinstaller",
    name="MyDesktopApp",
    entrypoint="main.py",
    one_file=True,
))
print(plan.command)  # Review the exact command before execution.
result = engine.execute(plan, trusted_workspace=True)
print(result.success, result.output_dir, result.output)
```

Plan creation is side-effect free. Execution requires an explicit trusted-workspace approval, runs argument arrays with `shell=False`, captures diagnostics, and has a bounded timeout. Only plans issued by the same engine instance can be executed; output and entrypoint paths are confined to the workspace. Project build hooks and packaging configuration are still executable code, so only package workspaces you trust.

This phase adds the packaging backend API and tests. A non-blocking Qt packaging workflow, progress/cancel UI, installer-specific configuration, signing, and release publishing are future work. No package is built automatically when a workspace is opened.
