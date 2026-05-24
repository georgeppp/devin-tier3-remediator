# Dependency Upgrade

## Workflow
1. Read `UPDATING.md` and the upstream changelog between current and target version.
2. List breaking changes that affect this codebase. If none, say so explicitly.
3. Update the version in the correct file (`requirements/*.txt` or `superset-frontend/package.json`).
4. If breaking changes exist, update call sites.
5. Run full test suite.
6. Run pre-commit.

## Stop conditions
- Version is updated in lock file too (`package-lock.json` or pip-compile output)
- All tests pass
- pre-commit exits 0
- PR description lists breaking changes found (or "none")
- PR title: `[Deps] Bump <name> <old> → <new>`

## Out of scope
No unrelated upgrades. No refactoring. If tests break in ways unrelated to the upgrade, document but don't fix.
