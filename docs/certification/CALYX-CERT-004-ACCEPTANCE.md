# Acceptance criteria

- A zero-commit repair response is never reported as applied.
- A write response without PR head advancement is reported as not applied.
- A verified head advancement with a commit is reported as committed and waiting for CI.
- Existing draft-only, bounded-attempt, no-merge, and no-deployment controls remain intact.
