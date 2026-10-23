---
name: deprecate
description: Deprecate a function, class, argument or command in canvodpy (decorator, warning text, docs, callers). Use when code is superseded, duplicated or left over and must stay until v2.0.0.
---

# Deprecate code

Deprecated code keeps working in every 1.x release and is removed in
v2.0.0. Delete code outright only when the user says so.

## 1. Find every user of it

```bash
just graph-affected <name>
```

Also search the demo notebooks (`demo/`), the docs (`docs/`) and
canvodpy-extensions. Move canvodpy's own callers to the replacement first;
nothing in a run may still call deprecated code.

## 2. Mark it

Use the decorator `deprecated` from
`packages/canvod-utils/src/canvod/utils/tools/deprecation.py`
(`from canvod.utils.tools import deprecated`). It emits `FutureWarning`,
which Python shows by default. A package that uses it lists canvod-utils
as a dependency.

The message says three things, in words a scientist understands:

```python
@deprecated(
    "`check_rinex` is left over from development and will be removed with "
    "the next major version. Use `check_day` instead."
)
```

1. it is left over from development (or why it is wrong, if it gives
   different results),
2. it will be removed with the next major version,
3. what to use instead.

A deprecated argument gets `deprecated_argument` (same module), which
warns when the argument is passed, with a message of the same three
parts:

```python
@deprecated_argument(
    "align",
    "The 'align' argument of from_datasets() is left over from development "
    "and will be removed with the next major version. Remove the argument.",
)
```

Leave the argument out of the docstring. A deprecated module says so in
its docstring and warns on use.

## 3. Same PR

- A test that the warning fires and that the old name still works
  (delegating to the replacement where possible).
- Docs: remove it from the guides and examples, teach the replacement.
  The API reference hides it on its own (`scripts/griffe_hide_deprecated.py`
  reads both decorators).
- The `AGENTS.md` of the package, if it names the code.
- Commit: `refactor(<scope>): deprecate <name>, use <replacement>`.
