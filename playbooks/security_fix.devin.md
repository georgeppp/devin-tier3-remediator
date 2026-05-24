# Security Fix

## Workflow
1. Locate the vulnerable code path. Read surrounding context.
2. Write a regression test that FAILS on current code.
3. Apply the minimal fix.
4. Confirm the test now passes.
5. Run `pytest tests/unit_tests/security/` and `pre-commit run --all-files`.

## Stop conditions (ALL must hold)
- Regression test exists and would fail on pre-fix code
- All security tests pass
- pre-commit exits 0
- PR title: `[Security] <one-line>`

## PR template
**Vulnerability:** <one paragraph>
**Fix:** <one paragraph>
**Regression test:** <file:line>
**Verification:** pytest passed, pre-commit passed

## Out of scope
No refactoring. No dep upgrades. No formatting changes outside touched files.
