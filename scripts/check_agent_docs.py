"""Check that the agent instructions name only paths and recipes that exist.

Reads ``AGENTS.md``, ``canvodpy/AGENTS.md``, ``packages/*/AGENTS.md``,
``.claude/skills/*/SKILL.md``, ``CODING_STANDARDS.md``, ``GLOSSARY.md``,
``docs/agents/*.md`` and ``docs/adr/*.md`` (what the agent workflow
reads). A path in backticks must exist relative to
the repository root, to the file's directory, or to the source folder of
the file's package (``src/canvod/<name>`` or ``src/canvodpy``), as the
package tables write them; a ``just <recipe>`` must be
a recipe of the root Justfile; a ``/<skill>`` must be a skill of
``.claude/skills/``, a ``/mattpocock-skills:<skill>`` a skill of the
plugin (Claude Code calls plugin skills only by their full name).
``extensions:<path>`` names a path in the
canvodpy-extensions repository; it is checked at the canvod-filemap commit
locked in ``uv.lock`` if a canvodpy-extensions git checkout is found
(``$CANVODPY_EXTENSIONS_REPO``, or ``canvodpy-extensions`` next to this
repository). Placeholders (``<...>``, ``PKG``, ``*``) and the paths listed
below are not checked.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

#: Paths outside this repository: git refs, temporary files, the user's home,
#: the locally built code graph.
OTHER_REPO_PREFIXES = ("origin/", "/tmp/", "~/", ".graphify/")

#: Prefix of a path in the canvodpy-extensions repository.
EXTENSIONS = "extensions:"

#: The user's own files (git-ignored), and the submodules, which a plain
#: checkout (CI) does not contain.
UNCHECKED_PREFIXES = (
    "config/canvod-settings.yaml",
    "canvod-settings.yaml",
    "demo/",
    "packages/canvod-readers/tests/test_data/",
)

#: Recipes of the canvodpy-extensions Justfile, named in the guides.
OTHER_REPO_RECIPES = frozenset({"lock-canvodpy", "release-package"})

#: Skills of the mattpocock-skills plugin (``just agent-skills``), version
#: 1.3.1. The files name them ``/mattpocock-skills:<name>``; update this
#: list when the plugin adds or renames one.
PLUGIN_SKILLS = frozenset({
    "ask-matt", "code-review", "codebase-design", "diagnosing-bugs",
    "domain-modeling", "grill-me", "grill-with-docs", "grilling", "handoff",
    "implement", "implement-spec", "improve-codebase-architecture", "pr",
    "prototype", "research", "retro", "setup-matt-pocock-skills", "tdd",
    "teach", "to-questionnaire", "to-spec", "to-tickets", "triage",
    "wait-what", "wayfinder", "wizard", "writing-for-agents",
})  # fmt: skip

_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
PLUGIN = "mattpocock-skills"
_SKILL = re.compile(r"/(?:(?P<plugin>[a-z][a-z0-9-]*):)?(?P<name>[a-z][a-z0-9-]*)")
_JUST = re.compile(r"(?:^|[\s`(])just ([a-z][a-z0-9-]*)(?![\w=-])")
_PATH_SUFFIXES = (".md", ".py", ".toml", ".yaml", ".yml", ".ini", ".lock", ".json")
_PLACEHOLDER = re.compile(r"[<>*{}]|PKG|X\.Y\.Z")


def agent_files() -> list[Path]:
    return [
        ROOT / "AGENTS.md",
        ROOT / "canvodpy" / "AGENTS.md",
        *sorted(ROOT.glob("packages/*/AGENTS.md")),
        *sorted(ROOT.glob(".claude/skills/*/SKILL.md")),
        ROOT / "CODING_STANDARDS.md",
        ROOT / "GLOSSARY.md",
        *sorted(ROOT.glob("docs/agents/*.md")),
        *sorted(ROOT.glob("docs/adr/*.md")),
    ]


def own_skills() -> frozenset[str]:
    """The skills of this repository, called as ``/name``."""
    return frozenset(
        p.name for p in (ROOT / ".claude" / "skills").iterdir() if p.is_dir()
    )


def skill_problem(span: str, plugin: str | None, name: str) -> str | None:
    """Return why ``span`` does not call a skill, or None."""
    if plugin is None:
        if name in own_skills():
            return None
        if name in PLUGIN_SKILLS:
            return f"`{span}` is a plugin skill; write `/{PLUGIN}:{name}`"
        return f"`{span}` is not a skill"
    if plugin != PLUGIN or name not in PLUGIN_SKILLS:
        return f"`{span}` is not a skill"
    return None


def search_roots(file: Path) -> list[Path]:
    """Folders a path named in ``file`` may be relative to."""
    package = file.parent
    return [
        ROOT,
        package,
        *sorted(package.glob("src/canvod/*/")),
        *sorted(package.glob("src/canvodpy/")),
    ]


def extensions_repo() -> Path | None:
    default = ROOT.parent / "canvodpy-extensions"
    repo = Path(os.environ.get("CANVODPY_EXTENSIONS_REPO", default))
    return repo if (repo / "packages" / "canvod-filemap").is_dir() else None


def extensions_reference() -> str:
    """The canvod-filemap commit locked in ``uv.lock``.

    Raises
    ------
    ValueError
        If canvod-filemap is not locked from git.
    """
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    for package in lock["package"]:
        if package["name"] == "canvod-filemap" and "git" in package.get("source", {}):
            return urlsplit(package["source"]["git"]).fragment
    raise ValueError("canvod-filemap is not locked from git in uv.lock")


def just_recipes() -> set[str]:
    out = subprocess.run(
        ["just", "--summary"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return set(out.split())


def is_path(span: str) -> bool:
    if " " in span or span.startswith(("http", "-")) or _PLACEHOLDER.search(span):
        return False
    return "/" in span or span.endswith(_PATH_SUFFIXES)


def git_object_exists(repo: Path, spec: str) -> bool:
    """Whether the git object ``spec`` exists in ``repo``.

    Git sets ``GIT_DIR`` and friends for hooks; they would point this call
    at this repository instead of ``repo``.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cmd = ["git", "-C", str(repo), "cat-file", "-e", spec]
    return subprocess.run(cmd, env=env, capture_output=True).returncode == 0


def problems(
    file: Path, recipes: set[str], extensions: tuple[Path, str] | None
) -> list[str]:
    text = file.read_text(encoding="utf-8")
    found = []
    for span in _CODE_SPAN.findall(_FENCE.sub("", text)):
        if span.startswith(EXTENSIONS):
            path = span.removeprefix(EXTENSIONS).rstrip("/")
            if extensions and not _PLACEHOLDER.search(path):
                repo, ref = extensions
                if not git_object_exists(repo, f"{ref}:{path}"):
                    found.append(
                        f"path `{path}` does not exist in canvodpy-extensions at {ref}"
                    )
            continue
        if skill := _SKILL.fullmatch(span):
            if reason := skill_problem(span, skill["plugin"], skill["name"]):
                found.append(reason)
            continue
        if not is_path(span) or span.startswith(
            OTHER_REPO_PREFIXES + UNCHECKED_PREFIXES
        ):
            continue
        if not any((root / span).exists() for root in search_roots(file)):
            found.append(f"path `{span}` does not exist")
    for recipe in _JUST.findall(text):
        if recipe not in recipes and recipe not in OTHER_REPO_RECIPES:
            found.append(f"`just {recipe}` is not a recipe")
    return found


def main() -> int:
    recipes = just_recipes()
    repo = extensions_repo()
    extensions = None
    if repo is None:
        print("No canvodpy-extensions checkout found: extensions paths not checked")
    else:
        ref = extensions_reference()
        if not git_object_exists(repo, f"{ref}^{{commit}}"):
            print(
                f"canvodpy-extensions {ref} is not in {repo}: fetch it (git -C {repo} fetch origin)"
            )
            return 1
        extensions = (repo, ref)
    failed = False
    for file in agent_files():
        if not file.is_file():
            print(f"{file.relative_to(ROOT)}: missing")
            failed = True
            continue
        for problem in problems(file, recipes, extensions):
            print(f"{file.relative_to(ROOT)}: {problem}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
