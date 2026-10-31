---
name: refactoring
description: Refactor architecture, simplify code, and improve maintainability without changing behavior
---
# Safe refactoring

- Establish current behavior and existing tests before restructuring.
- Keep changes cohesive and avoid unrelated formatting churn.
- Preserve public APIs unless the task explicitly requires a change.
- Prefer small modules with clear responsibilities over broad rewrites.
- Add or update regression tests and compare behavior after refactoring.
