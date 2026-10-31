# Security boundaries

Vibe Code runs AI-generated actions on your machine. These are the boundaries it enforces
and the ones it does not.

## Enforced

| Area | Boundary |
|------|----------|
| Filesystem | Agent tools are confined to the workspace root; paths are resolved and symlink escapes rejected. `.vibe-code/` state paths refuse symlinks. |
| Writes | Every agent write is recorded by `ChangeManager` (diff + rollback). Editor saves and replacements are atomic and refuse to overwrite externally modified files. |
| Destructive tools | `rollback_changes` and other destructive tools are wrapped by `ApprovalGuardTool`. Interactive runs ask; **background runs always deny** them. |
| Processes | Preview, validation and packaging commands are argument arrays with `shell=False` and timeouts. The model cannot supply commands; adapters own them. |
| Trust | Running tests/builds/packaging requires explicitly trusting the workspace (build scripts execute project code). Dependencies are never installed automatically. |
| Secrets → providers | Files matching sensitive names/suffixes/directories (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `.ssh/`, `.aws/`, credential files…) are excluded from context. Content and outgoing messages are scanned and `[REDACTED]` for private keys, AWS keys, `sk-…` keys, GitHub tokens, bearer tokens, JWTs and `password/secret/token = …` assignments. |
| Secrets → logs | API keys are never part of `repr()` of configs/providers; provider error text is sanitised and redacted before display. |
| Autonomy | Iteration, token and wall-clock budgets, per-task retry limits, loop detection, cancellation, and checkpoints for recovery. |
| State files | Checkpoints, task state and caches are written atomically; corrupted files are rejected or rebuilt instead of crashing. |

## Not enforced (limitations)

- Redaction is pattern-based; unusual secret formats can slip through. Keep secrets out of
  source files and use `.vibeignore` / `.vibe-code/context.json` `exclude` for anything sensitive.
- Code you approve, preview, build or package runs with your user's permissions; there is no
  sandbox or container isolation. Only trust workspaces you would run yourself.
- The provider endpoint receives selected project content. Use a local endpoint if code must
  not leave the machine.
- The API key is read from `VIBE_CODE_API_KEY`; it is not stored by the app, so protecting the
  environment (shell profile, CI secrets) is the user's responsibility.

## Reporting

Please report vulnerabilities privately to the repository owner rather than opening a public issue.
