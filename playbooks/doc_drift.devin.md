# Doc Drift Fix

## Workflow
1. Read the doc section flagged in the issue.
2. Verify the current state by actually running the commands described.
3. Update doc to match what actually works.
4. Run any in-doc code blocks to confirm they work.

## Stop conditions
- Updated commands have been executed and succeeded
- No content removed that's still accurate
- PR title: `[Docs] Update <section> in <file>`

## Out of scope
No formatting overhauls. No reorganization. Only the drifted content.
