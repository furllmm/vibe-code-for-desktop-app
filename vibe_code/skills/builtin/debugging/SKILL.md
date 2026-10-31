---
name: debugging
description: Diagnose bugs, crashes, runtime errors, build failures, and logs
---
# Debugging workflow

- Reproduce or inspect the reported failure before changing code.
- Read the relevant source and the full useful error context.
- State a testable hypothesis and make the smallest targeted change.
- Avoid masking exceptions or deleting tests to make failures disappear.
- Run the narrowest relevant test first, then broader validation where practical.
- Inspect the resulting logs and distinguish verified fixes from assumptions.
