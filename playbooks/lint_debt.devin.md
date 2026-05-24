# Lint Debt Fix

## Workflow
1. Run the failing linter on the target file to see exact violations.
2. Fix each violation. No logic changes.
3. Re-run the linter — must exit 0 on the target file.
4. Run the full test suite on affected modules.

## Stop conditions
- Linter exits 0 on the target file
- All tests in affected modules pass
- No behavioral changes
- PR title: `[Lint] Fix <linter> violations in <file>`

## Out of scope
No fixes outside the target file. No refactoring. No formatting changes that aren't lint-driven.
