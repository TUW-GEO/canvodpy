# canVODpy coding standards

Every change follows these. Read them before writing code;
`/mattpocock-skills:code-review` checks each change against them. The
reasons behind them are in `docs/adr/`. Rules a tool can check (ruff, ty,
`just check-agent-docs`, commitizen) are not repeated here: run
`just check`.

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

## Git and GitHub

These hold for every contributor's agent, whatever tool it is.

- **Every change reaches `main` through a pull request.** Work on a
  feature branch, never on `main`.
- **An agent may push its feature branch and open a pull request.**
  Nothing else: it never pushes `main` or a tag, never force-pushes,
  never deletes a remote branch or tag.
- **An agent never merges or approves a pull request.** A person reviews
  and merges, and pushes tags for releases.
- **No bypassing.** No `--no-verify` or `git commit -n`, no skipping,
  redirecting or removing the git hooks (`SKIP=`, `core.hooksPath`,
  `pre-commit uninstall`), no rewriting history that is already on
  GitHub, no changes to branch protection, rulesets, repository settings,
  CI or the agent settings to get a change through. If a check blocks a
  change, fix the change or ask the maintainers.

For Claude Code, `.claude/settings.json` enforces this with deny rules and
a hook (`scripts/agent_git_guard.py`) that blocks such commands. On
GitHub, a ruleset on `main` requires a pull request and passing checks,
and only maintainers can create, move or delete release tags (`v*`).

## Every change

1. **Before changing anything public**, list its callers
   (`just graph-affected NAME`) and search canvodpy-extensions and the demo
   notebooks for it; plan their change too.
2. **Tests with the code.** A bug fix gets a test that failed before the
   fix. Expected values come from an independent source (a worked example,
   the specification, measured data), never recomputed the way the code
   does it. A test that needs a person, a site or a position takes the
   made-up ones in `canvod.utils.testing`, never real people or sites.
   Tests never read the user's own settings: code that loads the settings
   itself gets the made-up ones (`testing.write_settings`, an autouse
   fixture in the root `conftest.py`).
3. **Docs in the same pull request**: the pages under `docs/` and the
   `AGENTS.md` files, wherever the change makes them wrong. A pull request
   that changes behavior (new logic, new code, changed code) without docs
   to match is declined. A new decision that is hard to reverse gets an
   ADR in `docs/adr/`; a new term gets a `GLOSSARY.md` entry. Every docs
   page the pull request changes passes Vale (`just docs-lint-changed`),
   and the built site passes the link check (`just docs-links`); CI runs
   both (`.github/workflows/docs_quality.yml`).
4. **Demo notebooks**: if the change breaks or outdates a notebook of
   canvodpy-demo (the `demo` submodule), adapt it there.
5. **Verify**: `just check`, then `just test-package <package>` for every
   package changed. Report failures; don't skip tests.
6. **Commit** on a feature branch in conventional form, scope = package or area:
   `fix(readers): ...`, `feat(store): ...`, `refactor(orchestrator): ...`.
   Mark breaking changes (`feat!:` or a `BREAKING CHANGE:` footer).
   Substantial agent help is credited with a `Co-Authored-By:` line.
   Push the branch and open a pull request; a person merges it
   (Git and GitHub, above).
7. **Real data and real stores**: running on real data or writing to a
   production store needs the maintainers' go-ahead first; see the
   `store-safety` guide.
