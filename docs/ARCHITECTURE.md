# Architecture

Vibe Code is a single-process PySide6 application. The GUI thread only renders and
dispatches; provider calls, agent loops, packaging and background runs execute on worker
threads (`QThread` or the `BackgroundTaskManager`) and report back through signals or
thread-safe snapshots.

```
vibe_code/
  app.py              MainWindow: toolbar, panels, wiring between services
  workspace/          Workspace model (root path, lifecycle)
  tools/              Workspace-scoped tools (read/write files, changes, preview) + ToolRegistry
  changes/            ChangeManager: snapshots every agent write, diff + rollback, Changes tab
  index/              ProjectIndexer (symbols, imports, dependency graph, git history), Index tab
  context/            ContextService (ranking + token budget), ContextSettings, Context tab
  security/           Secret redaction and sensitive-path rules shared by context + providers
  providers/          Provider interface + OpenAI-compatible Chat Completions adapter
  agent/              Agent loop, Enhance, task checkpoints, autonomous runner, background jobs
  chat/ editor/       Project chat, editor, selection edit/chat/insights, workspace search
  runtime/            Preview adapters (Python, CMake, Rust, Go, Java, .NET, Node/Electron), validation
  packaging/          Packaging backends (PyInstaller, CPack, AppImage…) for the *user's* project
  skills/ templates/  Built-in Markdown skills and project templates (package data)
```

## Request flow

1. **Index** — `ProjectIndexer.build_index()` walks the workspace (bounded: 20 000 files,
   512 KB per file, 256 MB total), skips dependency/build/generated files, extracts symbols
   and imports (Python via `ast`; Rust, C/C++, Go via comment/string-aware line extractors),
   resolves a dependency graph and reverse dependents, and counts recent git changes per file.
   Results are cached in `.vibe-code/index/index.json` keyed by size + mtime; corrupted or
   old-version caches are discarded and rebuilt.
2. **Context** — `ContextService` scores files against the request (names, symbols, graph
   neighbours, change history), drops excluded/sensitive paths, materialises the best symbol
   ranges within the token budget, adds project rules, and redacts secrets. The result is a
   `ContextPack` (files, index summary, redaction count, warnings).
3. **Provider** — `OpenAICompatibleProvider` redacts outgoing messages again, sends the
   request with timeout/retry/backoff/`Retry-After`, honours a cancel event and returns
   content, tool calls and token usage. Errors are `ProviderError` with sanitised messages.
4. **Tools** — the model can only call tools in the `ToolRegistry` allow-list. Every write
   goes through `ChangeManager` so it is diffable and reversible.
5. **Validation** — `ProjectValidator` runs the detected project's tests/build with argument
   arrays (`shell=False`) and a timeout, only when the user has trusted the workspace.

## Autonomous runs (Continue / Full Do)

`agent/autonomy.py` — `AutonomousRunner` asks the provider for a plan (JSON or bullet list;
falls back to one task), then executes tasks sequentially, each through the normal agent
loop. After every task it optionally validates; failures are retried up to
`max_retries_per_task`. The run stops on: all tasks done, cancellation, iteration/token/time
budget (`RunLimits`), or loop detection (the same state fingerprint repeating
`loop_window` times). Tasks end as `passed` (validated), `untested` (no validation ran),
`failed` or `skipped` — never reported as passed without validation.

Each step is written atomically (`tempfile` + `fsync` + `os.replace`) to
`.vibe-code/runs/<run_id>.json`; `resume(run_id)` continues from that checkpoint. Unknown
keys from other app versions are ignored on load.

`agent/background.py` — `BackgroundTaskManager` runs jobs on daemon threads, rejects a
second active job with the same key (`DuplicateTaskError`), propagates cancellation via
`threading.Event`, and captures worker exceptions. `agent/runs_panel.py` (Runs tab) starts,
monitors (status, current task, counts, budgets, log), cancels and resumes runs, and
surfaces interrupted checkpoints when a workspace is opened.

## Persistent state

All state lives in the workspace under `.vibe-code/` (git-ignored) or in environment
variables — nothing is written to the user profile. See [README](../README.md#configuration-and-state).
