---
title: Developing with coding agents
description: The instructions canVODpy gives coding agents such as Claude Code, the shared development workflow, how they stay correct, and the free code graph
---

# Developing with coding agents

canVODpy is developed with coding agents, mostly
[Claude Code](https://docs.anthropic.com/en/docs/claude-code). The
repository carries instructions for them, so that an agent works by the
same rules as a person and knows the science and the traps before it
changes code. You don't need an agent to contribute: the same files are a
compact summary of the project's conventions for people too.

Everything here works with free tools only. No step needs a paid service
or an API key.

---

## The instruction files

| File | What it holds |
|---|---|
| `AGENTS.md` (root) | Scientific context, packages, the one way to process data, data contracts, the development workflow, guardrails, and the reading order of these docs |
| `canvodpy/AGENTS.md`, `packages/<package>/AGENTS.md` | Per package: where things live, invariants and decisions, tests |
| `.claude/skills/<task>/SKILL.md` | Step-by-step guides for recurring tasks: run the pipeline, add a reader or constellation, deprecate code, store safety, the Icechunk 2 API, the link to canvodpy-extensions, releasing |
| `CLAUDE.md` files | One line, `@AGENTS.md`. Claude Code reads `CLAUDE.md`, other agents read `AGENTS.md` |
| `CODING_STANDARDS.md` | The rules every change follows and the checklist for each change; reviews check against it |
| `GLOSSARY.md` | The project's words, and the words to avoid ([Glossary](../glossary.md)) |
| `docs/adr/` | The decisions behind canVODpy and why they were made ([Decisions](../adr/index.md)) |
| `docs/agents/` | How the workflow skills below use GitHub issues, triage labels, and the glossary |
| `.claude/settings.json` | Enables the workflow plugin; blocks merging, pushing `main` or tags and bypassing checks (with `scripts/agent_git_guard.py`) |

Claude Code loads the root file at the start of a session, a package's
file when it works in that package, and a task guide when the task fits
its description. Other agents read the same Markdown files.

The files describe what cannot be seen quickly in the code: decisions,
invariants, where the truth lives. They point at the code instead of
copying it, so they go out of date less often.

### Kept correct by a check

Every path and `just` recipe named in these files must exist.
`just check-agent-docs` verifies this; it runs in `just check`, as a
pre-commit hook and in CI. Paths in canvodpy-extensions are written
`extensions:<path>` and checked at the extensions commit canvodpy is
locked to. A change that makes a statement wrong updates the file in the
same pull request.

---

## The development workflow

Contributors develop with one shared workflow: the open source
[mattpocock/skills](https://github.com/mattpocock/skills), a set of
skills for Claude Code. Each step guards against a typical failure of
agent-written code: the agent building something other than what you
meant, inventing its own words for things, leaving no record of why,
writing code without tests, or ignoring the project's rules.

Claude Code loads the skills when it is started in the canvodpy folder,
and calls them only by their full name, `/mattpocock-skills:<skill>`; a
short `/grill-with-docs` is an unknown command, and a short
The plain `/code-review` command is the review built into Claude Code.

| Situation | Start with | What happens |
|---|---|---|
| An idea or a change to design | `/mattpocock-skills:grill-with-docs` | The agent asks you questions in rounds, each with its recommended answer, until every decision is settled. New terms go to the glossary, decisions that are hard to reverse to `docs/adr/`. |
| A change too big for one session | `/mattpocock-skills:to-spec`, then `/mattpocock-skills:to-tickets` | The settled design becomes a GitHub issue (the spec), split into small tickets that each work on their own. |
| One ticket, or a change that fits one session | `/mattpocock-skills:implement` | Test first (`/mattpocock-skills:tdd`): a failing test, then the code that makes it pass. It ends with `/mattpocock-skills:code-review`. |
| Review a branch or pull request | `/mattpocock-skills:code-review` | Two separate reviews: against `CODING_STANDARDS.md`, and against the issue the change was made for. |
| Something is broken | `/mattpocock-skills:diagnosing-bugs` | First a command that shows the bug, then hypotheses, then the fix with a regression test. |
| After a session that went wrong | `/mattpocock-skills:retro` | Suggests checks and rules so the same mistake can't happen again. |
| Not sure which | `/mattpocock-skills:ask-matt` | Recommends the skill for your situation. |

The full flow is meant for real changes; a typo needs none of it. The
domain guides of canVODpy (add a reader, deprecate code, store safety and
the others) still apply inside any of these steps. Some skills run
helper agents in parallel (`/mattpocock-skills:code-review`,
`/mattpocock-skills:implement-spec`), which uses more of your agent's
quota.

---

## The code graph

`just graph` builds a graph of the code with
[graphify](https://pypi.org/project/graphifyy/): every module, class and
function, and who calls, imports, or subclasses whom. It is built from the
syntax tree on your machine in about ten seconds, needs no API key, and is
never committed (`.graphify/`). Git hooks rebuild it in the background
after each commit, merge and checkout.

```bash
just graph-affected add_cell_ids_to_ds_fast   # everything that uses it
just graph-explain VodComputer                # its neighbors, both directions
just graph-path VodComputer TauOmegaZerothOrder
```

Agents use it before changing or deprecating anything (to find every
caller) and before writing new code (to find an existing implementation).
Connections marked `INFERRED` are guesses; check them in the code.

graphify can also call paid language-model services. The `just` recipes
use only its free, local commands, and remove API keys from its
environment. Don't run other graphify commands (its output suggests
`graphify cluster-only`, which can call a paid service) or install its
assistant skill.

---

## Getting started

```bash
just sync          # dependencies and git hooks (including the graph rebuild)
just graph         # first build of the code graph
just agent-skills  # the workflow skills (Claude Code plugin); rerun to update
claude             # in the repository root
```

Start the agent in the repository root: it reads its instructions from
there. `.claude/settings.json` declares the plugin's marketplace and
enables the plugin, so Claude Code takes it from there once you trust the
repository folder; `just agent-skills` installs and updates it
explicitly. For
other coding agents, `npx skills@latest add mattpocock/skills` installs
the same skills.

---

## Guidelines for agent-assisted contributions

1. **Review all output.** A person reviews every change before it is
   merged and is responsible for it.
2. **Run the checks.** `just check` and the tests of the changed packages
   (`just test-package <package>`).
3. **Check scientific claims.** Agents can invent references, formulas or
   values. Compare with primary sources (IGS formats, interface control
   documents, the literature).
4. **Attribution.** Commits with substantial agent help say so in a
   `Co-Authored-By:` line.
5. **Agents don't merge.** An agent may push its feature branch and open
   a pull request; it never merges or approves one, never pushes `main` or
   tags, never force-pushes and never bypasses a check (`--no-verify`,
   skipped hooks, changed settings). Claude Code blocks these through
   `.claude/settings.json` and `scripts/agent_git_guard.py`; don't
   turn that off. See the Git and GitHub section of `CODING_STANDARDS.md`.
6. **No secrets.** Never give an agent credentials or private data. Hosted
   agents send what they read to their provider.

---

## Related pages

- [Architecture](../architecture.md): packages and data flow
- [API levels](api-levels.md): the command line and `Site.pipeline()`
- [Contributor setup](contributor-setup.md): setup and first run
