# Agents open pull requests; people merge

Every change reaches `main` through a pull request. An agent may push its
feature branch and open the pull request; it never merges or approves
one, never pushes `main` or a tag, never force-pushes, and never bypasses
a check (`--no-verify`, skipped hooks, changed protection or settings).
A person reviews every change, merges it and is responsible for it. The
rules are in `CODING_STANDARDS.md` (Git and GitHub) and hold for every
contributor's agent.

They are enforced in two places. On GitHub, a ruleset on `main` requires
a pull request and passing checks, and only maintainers can create, move
or delete release tags (`v*`); this is the only boundary that holds for
every tool. For Claude Code, `.claude/settings.json` adds deny rules and a
hook, `scripts/agent_git_guard.py`, that blocks the forbidden commands
before they run, also in modes that skip permission prompts.

## Considered options

- Letting agents merge once the checks pass would be faster, but the
  checks cannot tell whether a change is scientifically right; a person
  has to have looked at it.
- Forbidding agents to push at all would leave "an agent opens the pull
  request" impossible, since GitHub needs the branch first.
- Local settings alone cannot be enforced: a developer can edit or turn
  off anything on their own machine. They catch the agent's mistakes; the
  GitHub ruleset is what holds.
