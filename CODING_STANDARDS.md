# canVODpy coding standards

Every change follows these. Read them before writing code; `/code-review`
checks each change against them. The reasons behind them are in
`docs/adr/`. Rules a tool can check (ruff, ty, `just check-agent-docs`,
commitizen) are not repeated here: run `just check`.

## Rules

- **Free tools only.** Nothing in this project may need a paid service or
  API key: not for building, testing, docs or agent tooling. graphify can
  call paid language models; use it only through the `just graph*`
  recipes, never `graphify label`, `graphify cluster-only` (its output
  suggests it), a full `graphify extract`, or its assistant skill.
- **Explicit over implicit.** Fail loudly with a message that says what to
  do. No silent fallback, no hidden default: a default in a signature or a
  documented settings model is fine; library code reading the settings file
  behind the caller's back, or `except Exception` falling back to a value,
  is not. Entry points (CLI, `Site`) read the settings and pass them down.
- **One implementation per job.** Before writing something, find the code
  that already does it and reuse it (`just graph-explain` on the nearest
  name you know). Two code paths that do the same job drift apart and give
  different results.
- **Composition over inheritance.** Pass collaborators in; inherit only
  from pydantic models and from ABC interfaces. Interfaces are ABCs, not
  duck typing.
- **Deprecate, don't delete.** Public code that goes away gets the
  deprecation decorator and stays until v2.0.0; see the `deprecate` guide
  (`.claude/skills/deprecate/SKILL.md`). Delete outright only when the
  maintainers say so.
- **Optional processing stays optional.** Preprocessing from
  `processing.preprocessing` runs in every run when set and never by
  default.
- **Write for scientists.** Names, messages, CLI help and docs use clear,
  unambiguous words, the words of `GLOSSARY.md`.
- **Science changes are checked.** Changes in the guardrail areas listed in
  `AGENTS.md` need the science understood first, the primary source named
  (format specification, interface control document, paper), and
  `just test-fast` afterwards.

## Every change

1. **Before changing anything public**, list its callers
   (`just graph-affected NAME`) and search canvodpy-extensions and the demo
   notebooks for it; plan their change too.
2. **Tests with the code.** A bug fix gets a test that failed before the
   fix. Expected values come from an independent source (a worked example,
   the specification, measured data), never recomputed the way the code
   does it.
3. **Docs in the same pull request**: the pages under `docs/` and the
   `AGENTS.md` files, wherever the change makes them wrong. A new decision
   that is hard to reverse gets an ADR in `docs/adr/`; a new term gets a
   `GLOSSARY.md` entry.
4. **Demo notebooks**: if the change breaks or outdates a notebook of
   canvodpy-demo (the `demo` submodule), adapt it there.
5. **Verify**: `just check`, then `just test-package <package>` for every
   package changed. Report failures; don't skip tests.
6. **Commit** in conventional form, scope = package or area:
   `fix(readers): ...`, `feat(store): ...`, `refactor(orchestrator): ...`.
   Mark breaking changes (`feat!:` or a `BREAKING CHANGE:` footer).
   Substantial agent help is credited with a `Co-Authored-By:` line.
7. **Real data and real stores**: running on real data or writing to a
   production store needs the maintainers' go-ahead first; see the
   `store-safety` guide.
