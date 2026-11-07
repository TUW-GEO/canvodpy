## Summary

<!-- What changes and why, in the words of GLOSSARY.md. Show the smallest
view that makes the point: pseudocode, a call tree or a file tree.
Link the issue: Closes #... -->

## Evidence

<!-- Before and after: command output, a failing then passing test. -->

## Merge danger

**Door:** <!-- one-way (store format, removal, release) or two-way (can be reverted) -->

**Blast radius:** <!-- one word, e.g. docs, CLI, stores -->

## Checklist

- [ ] `just test && just check` pass
- [ ] Tests for every new function and error path
- [ ] Docs in `docs/` match the change
- [ ] The commit type matches the change (`fix` patch, `feat` minor, `!` major)
- [ ] No passwords, host names, user names or private paths in code, docs or output
