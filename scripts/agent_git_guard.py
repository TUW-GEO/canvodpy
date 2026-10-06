#!/usr/bin/env python3
"""Block git and GitHub commands that agents may not run.

Claude Code runs this before every shell command of an agent
(PreToolUse hook in `.claude/settings.json`). It reads the hook's JSON
from stdin and exits with 2, which blocks the command, when the command
breaks one of the rules of `CODING_STANDARDS.md` (Git and GitHub):

- every change reaches `main` through a pull request; an agent may push a
  feature branch to open one, nothing else: not `main`, not tags, never
  forced, never a deletion;
- an agent never merges or approves a pull request;
- no check is bypassed: no `--no-verify`, no skipped or removed hooks, no
  change to branch protection, rulesets or repository settings.

The check reads the command text, so it covers the forms agents write
(`sh -c`, `git -C`, chained commands), not every program that could talk
to git. GitHub's ruleset on `main` is the boundary that holds for every
tool; this hook stops the agent before it gets there.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

PROTECTED_BRANCHES = frozenset({"main", "master"})

# Commands are split at shell separators; each part is checked on its own.
_SEPARATOR = re.compile(r"&&|\|\||[;|&\n()`]|\$\(")

_PUSH_FLAGS_FORBIDDEN = {
    "--force": "a force push",
    "--force-with-lease": "a force push",
    "--force-if-includes": "a force push",
    "--mirror": "a mirror push",
    "--all": "pushing all branches",
    "--branches": "pushing all branches",
    "--tags": "pushing tags",
    "--follow-tags": "pushing tags",
    "--delete": "deleting a remote branch or tag",
    "--prune": "deleting remote branches",
    "--no-verify": "skipping the pre-push hook",
}
_PUSH_SHORT_FORBIDDEN = {"f": "a force push", "d": "deleting a remote branch or tag"}

_HOOK_BYPASS = [
    (re.compile(r"(?<![\w-])--no-verify\b"), "skipping the git hooks (--no-verify)"),
    (re.compile(r"(?<![\w-])SKIP="), "skipping pre-commit hooks (SKIP=)"),
    (
        re.compile(r"PRE_COMMIT_ALLOW_NO_CONFIG"),
        "running without the pre-commit config",
    ),
    (
        re.compile(r"\bhooksPath\b", re.IGNORECASE),
        "redirecting the git hooks (core.hooksPath)",
    ),
    (re.compile(r"\bpre-commit\s+uninstall\b"), "removing the git hooks"),
    (
        re.compile(
            r"\b(rm|mv|cp|ln|chmod|truncate|tee)\b[^;&|\n]*\.git/hooks|>\s*\S*\.git/hooks"
        ),
        "changing the git hooks directly",
    ),
    (re.compile(r"\bdisableAllHooks\b"), "turning off the Claude Code hooks"),
]

_GH_FORBIDDEN = [
    (re.compile(r"\bgh\s+pr\s+merge\b"), "merging a pull request"),
    (
        re.compile(r"\bgh\s+pr\s+review\b.*(?<![\w-])(--approve|-a)\b"),
        "approving a pull request",
    ),
    (
        re.compile(r"\bgh\s+repo\s+(edit|delete|rename|archive)\b"),
        "changing repository settings",
    ),
    (
        re.compile(r"\bgh\s+release\s+(create|edit|delete|upload)\b"),
        "changing a release",
    ),
    (re.compile(r"\bgh\s+ruleset\s+(create|edit|delete)\b"), "changing a ruleset"),
    (re.compile(r"\bgh\s+label\s+(delete|edit)\b"), "changing labels"),
]
_GH_API_SENSITIVE = re.compile(
    r"rulesets|/protection|/merges?\b|/collaborators|/hooks\b|/actions/permissions"
    r"|/git/refs|/releases|/environments"
    r"|mergePullRequest|AutoMerge|addPullRequestReview|createRef|updateRef|deleteRef"
)
_GH_API_WRITE = re.compile(
    r"(?<![\w-])(-X|--method)\s*=?\s*['\"]?(POST|PUT|PATCH|DELETE)\b"
    r"|(?<![\w-])(-f|-F|--field|--raw-field|--input)\b",
    re.IGNORECASE,
)


def _current_branch(cwd: str | None) -> str | None:
    """Return the checked-out branch, or None when detached or unknown."""
    try:
        out = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return out.stdout.strip() or None


def _push_problem(args: list[str], cwd: str | None) -> str | None:
    """Return why a `git push` with these arguments is not allowed."""
    positional: list[str] = []
    for arg in args:
        if arg.startswith("--"):
            flag = arg.split("=", 1)[0]
            if flag in _PUSH_FLAGS_FORBIDDEN:
                return _PUSH_FLAGS_FORBIDDEN[flag]
        elif arg.startswith("-") and len(arg) > 1:
            for letter, reason in _PUSH_SHORT_FORBIDDEN.items():
                if letter in arg[1:]:
                    return reason
        else:
            positional.append(arg)

    refspecs = positional[1:]  # positional[0] is the remote
    if not refspecs:
        branch = _current_branch(cwd)
        if branch is None:
            return "a push whose branch is unknown (detached HEAD); name the feature branch"
        refspecs = [branch]

    for spec in refspecs:
        if spec.startswith("+"):
            return "a force push (+refspec)"
        src, _, dst = spec.partition(":")
        if not src and dst:
            return "deleting a remote branch or tag"
        if src == "HEAD" and not dst:
            src = _current_branch(cwd) or "HEAD"
        target = (dst or src).removeprefix("refs/heads/")
        if target.startswith("refs/tags/") or re.fullmatch(r"v\d+(\.\d+)*\S*", target):
            return "pushing a tag"
        if target in PROTECTED_BRANCHES or target == "HEAD":
            return f"pushing to `{target}`"
    return None


def _git_subcommand(tokens: list[str]) -> tuple[str, list[str]] | None:
    """Return the git subcommand and its arguments, if the tokens run git."""
    if "git" not in tokens:
        return None
    rest = tokens[tokens.index("git") + 1 :]
    # skip git's own options (-C dir, -c key=value, --git-dir=...)
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in {"-C", "-c"} else 1
    if i >= len(rest):
        return None
    return rest[i], rest[i + 1 :]


def _commit_skips_hooks(args: list[str]) -> bool:
    """Return True for `git commit -n` (short for --no-verify)."""
    takes_value = {"-m", "-F", "-C", "-c", "-t", "--author", "--date"}
    previous = ""
    for arg in args:
        if (
            previous not in takes_value
            and re.fullmatch(r"-[a-zA-Z]+", arg)
            and "n" in arg[1:]
        ):
            return True
        previous = arg
    return False


def problems(command: str, cwd: str | None = None) -> list[str]:
    """Return every rule the command breaks (empty when it is allowed)."""
    found: list[str] = []
    for pattern, reason in _HOOK_BYPASS + _GH_FORBIDDEN:
        if pattern.search(command):
            found.append(reason)
    if re.search(r"\bgh\s+api\b", command) and _GH_API_SENSITIVE.search(command):
        if _GH_API_WRITE.search(command):
            found.append(
                "changing branch protection, rulesets, refs or settings via the GitHub API"
            )

    # `sh -c '...'` and `bash -c "..."` are checked as the commands they run
    texts = [command]
    for match in re.finditer(
        r"\b(?:ba|z)?sh\s+-c\s+(['\"])(.*?)\1", command, re.DOTALL
    ):
        texts.append(match.group(2))
    for text in texts:
        for part in _SEPARATOR.split(text):
            try:
                tokens = shlex.split(part, posix=True)
            except ValueError:
                tokens = part.split()
            git = _git_subcommand(tokens)
            if git is None:
                continue
            subcommand, args = git
            if subcommand == "push" and (reason := _push_problem(args, cwd)):
                found.append(reason)
            if subcommand == "commit" and _commit_skips_hooks(args):
                found.append("skipping the git hooks (git commit -n)")
    return list(dict.fromkeys(found))


def main() -> int:
    """Run as a Claude Code PreToolUse hook."""
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = (event.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return 0
    found = problems(command, event.get("cwd"))
    if not found:
        return 0
    print(
        "Blocked by the agent git guard (CODING_STANDARDS.md, Git and GitHub): "
        + "; ".join(found)
        + ". Agents may push a feature branch and open a pull request; "
        "a person reviews, merges, pushes main and tags. Ask the user.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
