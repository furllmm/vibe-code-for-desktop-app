# TODO / known gaps

Honest list of what is not done yet. See [docs/SECURITY.md](docs/SECURITY.md) for security limitations.

## Product
- [ ] Interactive approval for destructive tools inside background runs (currently always denied).
- [ ] Language-server integration (diagnostics, completion, go-to-definition) in the editor.
- [ ] Tree-sitter based extraction for Rust/C/C++/Go (current extractors are heuristic).
- [ ] Persist provider settings in a UI (currently environment variables only) with OS keyring storage for API keys.
- [ ] Responses API / non-OpenAI-native providers (Anthropic, Gemini) adapters.
- [ ] Percentage progress for packaging; AppImage backend that builds the AppDir itself.
- [ ] .NET multi-target / solution selection; Java classpath assembly in preview.

## Platform
- [ ] macOS testing and bundle (`.app`) — untested.
- [ ] Code signing for Windows/macOS bundles; installer (MSI/NSIS, `.deb`/Flatpak).
- [ ] Sandboxed execution of previews/validation (containers).

## Quality
- [ ] End-to-end tests against a real provider (current tests use fake providers).
- [ ] Type checking (mypy/pyright) and lint in CI.
