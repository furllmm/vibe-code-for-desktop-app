# Coding templates

Templates are starting points, not permission to overwrite an existing workspace.

## Initial template catalog

- `python-pyside6`: a small Qt desktop application with a clear entry point.
- `cpp-qt`: C++ desktop app using Qt and a CMake build.
- `cpp-sdl`: interactive C/C++ app using SDL.
- `rust-egui`: Rust desktop app using egui/eframe.
- `go-gui`: Go desktop app using a supported GUI framework.
- `dotnet-avalonia`: cross-platform .NET desktop UI.
- `electron`: Electron desktop application.
- `settings-page`: reusable settings feature concept.
- `dashboard`: desktop dashboard feature concept.
- `plugin`: plugin architecture feature concept.
- `ai-agent`: provider-neutral agent feature concept.

A future template manifest should specify template ID/version, target toolchain, required tools,
files to generate, variables, included rules/skills, and whether destination files would be overwritten.
Template application must show a preview/diff and request approval before replacing files.
