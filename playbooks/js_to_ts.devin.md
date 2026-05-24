# JavaScript to TypeScript Migration

## Workflow
1. Read the target `.js` file fully.
2. Rename to `.ts` (or `.tsx` if it contains JSX).
3. Add explicit types. Use `unknown` not `any` when uncertain.
4. Update imports across the codebase if extension matters.
5. Run `cd superset-frontend && npm run type` and `npm test`.

## Stop conditions
- File compiles with no TS errors
- All existing tests still pass — behavior is unchanged
- No `any` introduced (use `unknown` if truly unknown)
- PR title: `[Migration] Convert <file> to TypeScript`

## Out of scope
No behavioral changes. No refactoring. No additional features.
