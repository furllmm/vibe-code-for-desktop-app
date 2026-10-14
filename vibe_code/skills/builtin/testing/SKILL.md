---
name: testing
description: Add automated tests, validate edge cases, and improve regression coverage
---
# Testing and validation

- Derive tests from user-visible behavior and acceptance criteria.
- Cover normal cases, invalid input, boundaries, and failure paths.
- Prefer deterministic unit tests and fake external services over network calls.
- Do not weaken or remove a test merely to get a green result.
- Report commands actually run and never claim unexecuted tests passed.
