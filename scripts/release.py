# /// script
# requires-python = ">=3.14"
# dependencies = ["packaging>=25"]
# ///
"""Prepare a release of chosen packages at chosen versions.

Every package has its own version. The maintainer chooses which packages to
release and at which version; this script only checks and applies the
choice. ``canvodpy`` is the umbrella: it pins every package exactly
(``canvod-store==1.1.0``), so it is part of every release, and its increment
is at least the largest increment of the packages released with it.

Commands
--------
``status``
    For each package: version, last release tag, and the commits since that
    tag that touched the package's folder. Helps to choose the versions.
``prepare NAME=VERSION ...``
    Checks the choice, writes the versions, canvodpy's pins and a changelog
    section per package (from the commits that touched its folder), canvodpy's
    version and the release date in the citation files (Zenodo reads the
    version from them), runs ``uv lock`` and commits exactly these files on
    ``release/v<canvodpy version>``. No tag.
``tag``
    On the merged release commit: creates the annotated tags of every package
    whose version has no tag yet (``canvod-store-v1.1.0``; ``v1.1.0`` for
    canvodpy). Does not push.
``push``
    On the merged release commit: pushes its release tags that origin lacks,
    canvodpy's on its own first (more than three tags in one push start no
    workflow, so the draft release would not appear), with
    ``--no-follow-tags``.
``check VERSION``
    Read-only: checks that the repository is ready for ``prepare`` of
    canvodpy ``VERSION`` (main and CI, the version and its increment, the
    submodule pointers, the demo notebook headers, the release notebook).
    One line per check (✓, ⚠, ✗); exits 1 if any check fails.
``tagged``
    Prints the packages whose release tag points at HEAD: what the publish
    workflows build.

Tags: ``<package>-vX.Y.Z`` for the packages, ``vX.Y.Z`` for canvodpy (only
these create a GitHub release, see ``.github/workflows/release.yml``).
Before per-package versions, all packages were released together under
``vX.Y.Z``; a package without a tag of its own counts from the last of those.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
UMBRELLA = "canvodpy"

#: Conventional-commit type -> changelog heading, in output order.
SECTIONS = {
    "feat": "Feat",
    "fix": "Fix",
    "perf": "Perf",
    "refactor": "Refactor",
}
OTHER = "Other"
SUBJECT = re.compile(
    r"^(?P<type>\w+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<text>.+)$"
)
INSERTION_MARKER = "<!-- insertion marker -->"

#: Citation file -> (version field, date field), each a pattern whose group 1
#: is kept and whose value is replaced. They describe canvodpy as a whole, so
#: they carry canvodpy's version; Zenodo reads the version of a record from
#: ``CITATION.cff`` and ``.zenodo.json``.
CITATION_FIELDS = {
    "CITATION.cff": (r"(?m)^(version: ).*$", r"(?m)^(date-released: ).*$"),
    ".zenodo.json": (r'("version": )"[^"]*"', r'("publication_date": )"[^"]*"'),
    "codemeta.json": (r'("version": )"[^"]*"', r'("datePublished": )"[^"]*"'),
}


@dataclass
class Package:
    name: str
    folder: Path

    @property
    def pyproject(self) -> Path:
        return self.folder / "pyproject.toml"

    @property
    def changelog(self) -> Path:
        # canvodpy's changelog is the repository's, one folder up.
        folder = self.folder.parent if self.name == UMBRELLA else self.folder
        return folder / "CHANGELOG.md"

    @property
    def version(self) -> Version:
        return Version(tomllib.loads(self.pyproject.read_text())["project"]["version"])

    def tag(self, version: Version | str) -> str:
        return f"v{version}" if self.name == UMBRELLA else f"{self.name}-v{version}"

    def requirements(self) -> list[Requirement]:
        """The package's requirements on other canVODpy packages."""
        data = tomllib.loads(self.pyproject.read_text())
        project = data["project"]
        lines = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            lines += extra
        for group in data.get("dependency-groups", {}).values():
            lines += [line for line in group if isinstance(line, str)]
        reqs = [Requirement(line) for line in lines]
        return [req for req in reqs if req.name.startswith("canvod")]


def _packages(root: Path = ROOT) -> dict[str, Package]:
    found = {UMBRELLA: Package(UMBRELLA, root / "canvodpy")}
    for pyproject in sorted(root.glob("packages/*/pyproject.toml")):
        name = tomllib.loads(pyproject.read_text())["project"]["name"]
        found[name] = Package(name, pyproject.parent)
    return found


def _git_env(root: Path) -> dict[str, str]:
    """The environment of git: the project's virtual environment first on PATH.

    ``git switch`` and ``git commit`` run the pre-commit hooks, which look for
    ``pre-commit`` on PATH when the Python they were installed with is gone;
    without it on PATH the hook fails and so does the git command.
    """
    env = dict(os.environ)
    for scripts in (root / ".venv" / "bin", root / ".venv" / "Scripts"):
        if scripts.is_dir():
            env["PATH"] = f"{scripts}{os.pathsep}{env.get('PATH', '')}"
    return env


def _git(*args: str, root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, env=_git_env(root)
    )
    if result.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


def _branch_taken(branch: str, root: Path = ROOT) -> bool:
    """Whether ``branch`` exists locally or as a remote-tracking branch."""
    refs = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname)",
            f"refs/heads/{branch}",
            f"refs/remotes/*/{branch}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return bool(refs.strip())


def _last_tag(pkg: Package) -> str | None:
    """The package's newest release tag reachable from HEAD.

    A package without a tag of its own falls back to the newest canvodpy
    tag: until per-package versions, all packages were released together.
    """
    for pattern in (pkg.tag("*"), "v*"):
        tags = _git("tag", "--merged", "HEAD", "--list", pattern, "--sort=-v:refname")
        if tags:
            return tags.splitlines()[0]
    return None


def _commits(pkg: Package, since: str | None) -> list[tuple[str, str]]:
    """(short hash, subject) of the non-merge commits touching the package."""
    rev = f"{since}..HEAD" if since else "HEAD"
    out = _git(
        "log",
        "--no-merges",
        "--format=%h%x09%s",
        rev,
        "--",
        str(pkg.folder.relative_to(ROOT)),
    )
    commits = []
    for line in out.splitlines():
        short, _, subject = line.partition("\t")
        commits.append((short, subject))
    return commits


def _last_final(pkg: Package, root: Path = ROOT) -> Version | None:
    """The package's newest final (not pre-release) version among its tags.

    Like ``_last_tag``, a package without a final tag of its own falls back to
    the canvodpy tags.
    """
    for prefix in (pkg.tag(""), "v"):
        tags = _git("tag", "--merged", "HEAD", "--list", f"{prefix}*", root=root)
        versions = []
        for tag in tags.splitlines():
            try:
                versions.append(Version(tag.removeprefix(prefix)))
            except InvalidVersion:
                continue
        finals = [v for v in versions if not v.is_prerelease]
        if finals:
            return max(finals)
    return None


def _increment_from_final(pkg: Package, new: Version, root: Path = ROOT) -> int:
    """The increment of ``new`` over the package's last final version.

    From a pre-release (``1.0.0b1``) to its final (``1.0.0``) the release
    numbers don't change, so the increment counts from the version before.
    """
    old = pkg.version
    if old.is_prerelease:
        old = _last_final(pkg, root) or old
    return _increment(old, new)


def _increment(old: Version, new: Version) -> int:
    """0 patch, 1 minor, 2 major (as semantic versioning reads them)."""
    if new.major != old.major:
        return 2
    if new.minor != old.minor:
        return 1
    return 0


def status(packages: dict[str, Package]) -> int:
    for pkg in packages.values():
        since = _last_tag(pkg)
        commits = _commits(pkg, since)
        print(
            f"{pkg.name} {pkg.version}  (since {since or 'the first commit'}: {len(commits)} commits)"
        )
        for short, subject in commits:
            print(f"    {short} {subject}")
    return 0


def _changelog_section(
    pkg: Package,
    version: Version,
    commits: list[tuple[str, str]],
    pins: dict[str, str] | None = None,
    released: frozenset[str] = frozenset(),
) -> str:
    groups: dict[str, list[str]] = {}
    breaking: list[str] = []
    for short, subject in commits:
        match = SUBJECT.match(subject)
        if match is None:
            groups.setdefault(OTHER, []).append(f"- {subject} ({short})")
            continue
        scope = f"**{match['scope']}**: " if match["scope"] else ""
        line = f"- {scope}{match['text']} ({short})"
        if match["bang"]:
            breaking.append(line)
        groups.setdefault(SECTIONS.get(match["type"], OTHER), []).append(line)

    out = [f"## {pkg.tag(version)} ({dt.date.today().isoformat()})", ""]
    if breaking:
        out += ["### BREAKING CHANGES", "", *breaking, ""]
    for heading in [*SECTIONS.values(), OTHER]:
        if heading in groups:
            out += [f"### {heading}", "", *groups[heading], ""]
    if pins is not None:
        out += ["### Packages", ""]
        out += [
            f"- {name} {pin}{' (new)' if name in released else ''}"
            for name, pin in sorted(pins.items())
        ]
        out.append("")
    if len(out) == 2:
        out += ["No changes in this package's folder.", ""]
    return "\n".join(out)


def _write_changelog(pkg: Package, section: str) -> None:
    path = pkg.changelog
    if not path.exists():
        path.write_text(f"# Changelog\n\n{INSERTION_MARKER}")
    text = path.read_text()
    if INSERTION_MARKER not in text:
        raise SystemExit(
            f"{path.relative_to(ROOT)} has no '{INSERTION_MARKER}' line to insert at."
        )
    section = section.rstrip("\n") + "\n"
    path.write_text(text.replace(INSERTION_MARKER, f"{INSERTION_MARKER}\n{section}", 1))


def _set_version(pkg: Package, version: Version) -> None:
    text = pkg.pyproject.read_text()
    new, count = re.subn(
        r'(?m)^version = "[^"]+"', f'version = "{version}"', text, count=1
    )
    if count != 1:
        raise SystemExit(f"No version line in {pkg.pyproject.relative_to(ROOT)}.")
    pkg.pyproject.write_text(new)


def _set_pin(umbrella: Package, name: str, version: Version) -> None:
    text = umbrella.pyproject.read_text()
    new, count = re.subn(rf'"{re.escape(name)}==[^"]+"', f'"{name}=={version}"', text)
    if count == 0:
        raise SystemExit(
            f"canvodpy does not pin {name} (no '{name}==' in canvodpy/pyproject.toml)."
        )
    umbrella.pyproject.write_text(new)


def _missing_citation_fields(root: Path = ROOT) -> list[str]:
    """The citation files and fields ``_set_citation`` cannot find."""
    missing = []
    for name, fields in CITATION_FIELDS.items():
        path = root / name
        if not path.exists():
            missing.append(f"{name} is missing.")
            continue
        text = path.read_text()
        missing += [
            f"{name} has no field matching {field!r}."
            for field in fields
            if re.search(field, text) is None
        ]
    return missing


def _set_citation(version: Version, date: dt.date, root: Path = ROOT) -> None:
    """Write canvodpy's version and the release date into the citation files."""
    for name, (version_field, date_field) in CITATION_FIELDS.items():
        path = root / name
        text = path.read_text()
        # The date is quoted everywhere; the version only in the JSON files.
        quoted_version = str(version) if name == "CITATION.cff" else f'"{version}"'
        values = {version_field: quoted_version, date_field: f'"{date.isoformat()}"'}
        for field, value in values.items():
            text, count = re.subn(field, lambda m, v=value: f"{m[1]}{v}", text, count=1)
            if count != 1:
                raise SystemExit(
                    f"{name} has no field matching {field!r}; add it before releasing."
                )
        path.write_text(text)


def _release_files(packages: dict[str, Package], root: Path = ROOT) -> list[Path]:
    files = [root / "pyproject.toml", root / "uv.lock"]
    files += [root / name for name in CITATION_FIELDS]
    for pkg in packages.values():
        files += [pkg.pyproject, pkg.changelog]
    return files


def _range_problems(
    packages: dict[str, Package], chosen: dict[str, Version]
) -> list[str]:
    """Requirements between the packages that the released versions don't meet.

    A package left out of the release keeps its current version, and that
    version must still fit every range, or PyPI gets requirements nobody can
    install.
    """
    problems = []
    for pkg in packages.values():
        if pkg.name == UMBRELLA:
            continue
        for req in pkg.requirements():
            if req.name not in packages:
                continue
            version = chosen.get(req.name, packages[req.name].version)
            if req.specifier.contains(version, prereleases=True):
                continue
            if req.name in chosen:
                problems.append(
                    f"{pkg.name} requires {req}, which excludes {req.name} {version}: "
                    f"check {pkg.name} against the new version and widen its range by hand."
                )
            else:
                problems.append(
                    f"{pkg.name} requires {req}, which excludes the current "
                    f"{req.name} {version}: release {req.name} too, or widen the range."
                )
    return problems


def _push_groups(tags: list[str]) -> list[list[str]]:
    """The release tags in pushes: canvodpy's tag on its own, first.

    GitHub creates no push event for tags when more than three tags are
    pushed at once, so a canvodpy tag pushed with the package tags never
    starts the workflow that drafts its GitHub release.
    """
    # canvodpy's tags are "v<version>", the packages' "<name>-v<version>".
    umbrella = [name for name in tags if name[:1] == "v" and name[1:2].isdigit()]
    others = [name for name in tags if name not in umbrella]
    return [group for group in (umbrella, others) if group]


#: Without it, git pushes every annotated tag on the pushed commits when the
#: repository sets push.followTags, all in one push.
PUSH_TAGS = ("push", "--no-follow-tags", "origin")


def _push_commands(tags: list[str]) -> list[str]:
    """The ``git push`` commands of :func:`_push_groups`."""
    return [f"git {' '.join(PUSH_TAGS)} {' '.join(g)}" for g in _push_groups(tags)]


KINDS = ("patch", "minor", "major")


def _refusals(
    packages: dict[str, Package], chosen: dict[str, Version], root: Path = ROOT
) -> list[str]:
    """Why ``prepare`` refuses ``chosen``; ``check`` reports the same reasons."""
    problems = []
    for name, new in chosen.items():
        old = packages[name].version
        if new <= old:
            problems.append(f"{name}: {new} is not above the current {old}.")
        if _git("tag", "--list", packages[name].tag(new), root=root):
            problems.append(f"{name}: tag {packages[name].tag(new)} exists already.")
    if UMBRELLA in chosen and not problems:
        umbrella_step = _increment_from_final(
            packages[UMBRELLA], chosen[UMBRELLA], root
        )
        for name, new in chosen.items():
            step = _increment_from_final(packages[name], new, root)
            if step > umbrella_step:
                problems.append(
                    f"{name} makes a {KINDS[step]} release, canvodpy only a {KINDS[umbrella_step]}: "
                    "canvodpy's increment must be at least the largest one of its packages."
                )
    problems += _range_problems(packages, chosen)
    if UMBRELLA in chosen and _branch_taken(f"release/v{chosen[UMBRELLA]}", root=root):
        problems.append(
            f"The branch release/v{chosen[UMBRELLA]} exists already (locally or on a "
            "remote, as of your last `git fetch`); the release commit goes on a new "
            "branch of that name. Delete the old branch first."
        )
    problems += [
        f"{problem} Zenodo reads the version from it; add it before releasing."
        for problem in _missing_citation_fields(root)
    ]
    files = [str(f.relative_to(root)) for f in _release_files(packages, root)]
    # Not _git: it strips the output, and with it the status column of line 1.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", *files],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    if dirty.strip():
        names = ", ".join(line[3:] for line in dirty.splitlines() if line)
        problems.append(
            f"Release files have uncommitted changes; commit or discard them first: {names}"
        )
    return problems


def prepare(packages: dict[str, Package], args: list[str]) -> int:
    chosen: dict[str, Version] = {}
    for arg in args:
        name, sep, version = arg.partition("=")
        if not sep or name not in packages:
            print(
                f"Expected NAME=VERSION with NAME one of: {', '.join(packages)}; got '{arg}'."
            )
            return 2
        try:
            chosen[name] = Version(version)
        except InvalidVersion:
            print(f"{name}: '{version}' is not a version (expected e.g. 1.2.0).")
            return 2

    problems = []
    if UMBRELLA not in chosen:
        problems.append(
            "canvodpy pins every package, so it is part of every release: add canvodpy=X.Y.Z."
        )
    problems += _refusals(packages, chosen)
    if problems:
        print("Not released:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    umbrella = packages[UMBRELLA]
    for name, new in chosen.items():
        pkg = packages[name]
        if name != UMBRELLA:
            _set_version(pkg, new)
            _set_pin(umbrella, name, new)
            _write_changelog(
                pkg, _changelog_section(pkg, new, _commits(pkg, _last_tag(pkg)))
            )
    _set_version(umbrella, chosen[UMBRELLA])
    _set_citation(chosen[UMBRELLA], dt.date.today())
    pins = {req.name: str(req.specifier) for req in umbrella.requirements()}
    commits = _commits(umbrella, _last_tag(umbrella))
    section = _changelog_section(
        umbrella, chosen[UMBRELLA], commits, pins, frozenset(chosen)
    )
    _write_changelog(umbrella, section)

    subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    branch = f"release/v{chosen[UMBRELLA]}"
    released = ", ".join(
        f"{name} {version}" for name, version in chosen.items() if name != UMBRELLA
    )
    message = f"bump: canvodpy {chosen[UMBRELLA]}" + (
        f" ({released})" if released else ""
    )
    _git("switch", "-c", branch)
    _git(
        "add",
        "--",
        *[str(f.relative_to(ROOT)) for f in _release_files(packages) if f.exists()],
    )
    _git("commit", "-m", message)

    tags = [packages[name].tag(version) for name, version in chosen.items()]
    print(f"\n{message}\nprepared on branch {branch}.\n")
    print("Next steps (docs/RELEASING.md):")
    print(
        "  1. Review the commit and edit the changelog sections if needed: git show --stat"
    )
    print("  2. Push the branch and open a pull request; a maintainer merges it")
    print("  3. A maintainer tags the merged commit on main and pushes the tags:")
    print("       git switch main && git pull origin main && just tag-release")
    print("       just push-release-tags   # does:")
    for command in _push_commands(tags):
        print(f"         {command}")
    print("  4. GitHub Actions drafts the GitHub release of the canvodpy tag")
    print("  5. PyPI is separate and manual:")
    print(
        "       gh workflow run publish_pypi.yml "
        f"--ref {packages[UMBRELLA].tag(chosen[UMBRELLA])}"
    )
    print(
        "     It publishes the packages whose release tag points at that commit "
        f"(release.py tagged): {' '.join(chosen)}"
    )
    return 0


def tag(packages: dict[str, Package], root: Path = ROOT) -> int:
    if _git("status", "--porcelain", "--untracked-files=no", root=root):
        print("The working tree has uncommitted changes; tag a clean checkout of main.")
        return 1
    created = []
    for pkg in packages.values():
        name = pkg.tag(pkg.version)
        if _git("tag", "--list", name, root=root):
            continue
        _git("tag", "-a", name, "-m", f"Release {pkg.name} {pkg.version}", root=root)
        created.append(name)
    if not created:
        print("Every package version is tagged already.")
        return 0
    print("Created (not pushed):")
    for name in created:
        print(f"  {name}")
    print("\nPush them with: just push-release-tags. It does:")
    for command in _push_commands(created):
        print(f"  {command}")
    return 0


def _tags_at_head(packages: dict[str, Package], root: Path = ROOT) -> dict[str, str]:
    """Package name to its release tag, for the release tags that point at HEAD."""
    head = _git("rev-parse", "HEAD", root=root)
    found = {}
    for pkg in packages.values():
        tag_name = pkg.tag(pkg.version)
        if (
            _git("tag", "--list", tag_name, root=root)
            and _git("rev-list", "-n", "1", tag_name, root=root) == head
        ):
            found[pkg.name] = tag_name
    return found


def push(packages: dict[str, Package], root: Path = ROOT) -> int:
    """Push the release tags at HEAD that origin lacks, canvodpy's first."""
    _git("fetch", "--quiet", "origin", "main", root=root)
    if _git("rev-parse", "HEAD", root=root) != _git(
        "rev-parse", "origin/main", root=root
    ):
        print("HEAD is not origin/main: push the tags of the merged release commit.")
        return 1
    tags = list(_tags_at_head(packages, root).values())
    if not tags:
        print("No release tag points at HEAD: run just tag-release first.")
        return 1
    listed = _git("ls-remote", "--tags", "origin", root=root).splitlines()
    on_origin = {
        line.split("refs/tags/", 1)[1] for line in listed if "refs/tags/" in line
    }
    missing = [name for name in tags if name not in on_origin]
    if not missing:
        print("Every release tag at HEAD is on origin already.")
        return 0
    for group in _push_groups(missing):
        print(f"git {' '.join(PUSH_TAGS)} {' '.join(group)}")
        _git(*PUSH_TAGS, *group, root=root)
    print(
        "\nPushed. The canvodpy tag drafts the GitHub release "
        "(.github/workflows/release.yml); review and publish it."
    )
    return 0


def tagged(packages: dict[str, Package], root: Path = ROOT) -> int:
    """Print the packages whose release tag points at HEAD (for publishing)."""
    names = list(_tags_at_head(packages, root))
    if not names:
        print("No package's release tag points at this commit.", file=sys.stderr)
        return 1
    print(" ".join(names))
    return 0


# ---------------------------------------------------------------------------
# check: is the repository ready for ``prepare``? (docs/RELEASING.md)
# ---------------------------------------------------------------------------

#: The status of a check, printed at the start of its line.
PASS, WARN, FAIL = "✓", "⚠", "✗"
#: What ``Remote.ci`` returns.
CI_PASSED, CI_FAILED, CI_RUNNING, CI_NONE = "success", "failure", "pending", "none"
DEMO = "demo"
TEST_DATA = "packages/canvod-readers/tests/test_data"
#: A deprecation commit says so first: "refactor(config): deprecate ...".
DEPRECATION = re.compile(r"^deprecate\b", re.IGNORECASE)
#: A breaking change is marked by "!" or by this footer (conventional commits).
BREAKING = re.compile(r"(?m)^BREAKING[ -]CHANGE:")
#: Commit types that change no behavior: their subject never makes a deprecation.
NO_BEHAVIOR = {"docs", "test", "ci", "chore", "build", "style"}
#: Commit types a release notebook may have to describe.
NOTABLE = {"feat", "fix"}
MERGED_PR = re.compile(
    r"^Merge pull request #(?P<number>\d+) from [^/\s]+/(?P<branch>\S+)"
)
SQUASHED_PR = re.compile(r"\s*\(#(?P<number>\d+)\)$")
#: Who commits a pull request squashed or rebased on GitHub.
GITHUB_COMMITTER = "GitHub"
#: The forms of canvodpy's release tags: X.Y.Z, or a pre-release such as 1.2.0rc1.
RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")
HEADER = re.compile(r"(?ms)^# /// script\n(?P<body>.*?)^# ///$")
GITHUB = re.compile(r"github\.com[:/](?P<repository>[^/]+/[^/]+?)(?:\.git)?$")


@dataclass
class Check:
    status: str  # PASS, WARN or FAIL
    text: str


class Remote(ABC):
    """What only GitHub knows. ``GitHubRemote`` asks it; tests pass a fake."""

    @abstractmethod
    def main_head(self, url: str) -> str | None:
        """The commit ``main`` of the repository at ``url`` points at."""

    @abstractmethod
    def tags_at(self, url: str, sha: str) -> list[str]:
        """The tags of the repository at ``url`` that point at ``sha``."""

    @abstractmethod
    def ci(self, sha: str) -> str:
        """CI of canvodpy's commit ``sha``: CI_PASSED, CI_FAILED, CI_RUNNING or CI_NONE."""


class GitHubRemote(Remote):
    """The remote through ``git ls-remote`` and the ``gh`` command line."""

    def __init__(self, repository: str) -> None:
        self.repository = repository  # owner/name of canvodpy on GitHub

    @classmethod
    def from_origin(cls, origin: str) -> GitHubRemote:
        match = GITHUB.search(origin)
        if match is None:
            raise SystemExit(
                f"origin is {origin}, not a GitHub repository; release-check asks "
                "GitHub for main and CI."
            )
        return cls(match["repository"])

    @staticmethod
    def _run(*command: str) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except FileNotFoundError:
            raise SystemExit(
                f"{command[0]} is not installed; release-check needs git and the "
                "GitHub command line (gh, signed in with gh auth login)."
            ) from None
        except subprocess.CalledProcessError as error:
            raise SystemExit(
                f"{' '.join(command)} failed:\n{error.stderr.strip()}"
            ) from None
        return result.stdout

    def _ls_remote(self, *args: str) -> list[list[str]]:
        out = self._run("git", "ls-remote", *args)
        return [line.split("\t", 1) for line in out.splitlines() if line]

    def main_head(self, url: str) -> str | None:
        refs = self._ls_remote(url, "refs/heads/main")
        return refs[0][0] if refs else None

    def tags_at(self, url: str, sha: str) -> list[str]:
        # An annotated tag is listed twice; "^{}" marks the commit it points at.
        return [
            ref.removeprefix("refs/tags/").removesuffix("^{}")
            for commit, ref in self._ls_remote("--tags", url)
            if commit == sha
        ]

    def ci(self, sha: str) -> str:
        out = self._run(
            "gh",
            "api",
            "--paginate",
            f"repos/{self.repository}/commits/{sha}/check-runs",
            "--jq",
            ".check_runs[] | [.status, .conclusion] | @tsv",
        )
        runs = [line.split("\t") for line in out.splitlines() if line]
        if not runs:
            return CI_NONE
        if any(status != "completed" for status, _ in runs):
            return CI_RUNNING
        passed = {"success", "skipped", "neutral"}
        return CI_PASSED if all(c in passed for _, c in runs) else CI_FAILED


def _show(root: Path, path: str, rev: str = "HEAD") -> str | None:
    """The file ``path`` as committed in ``rev``; ``None`` if it isn't there."""
    shown = subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True
    )
    return None if shown.returncode else shown.stdout


def _submodule_urls(root: Path) -> dict[str, str]:
    """Submodule path -> URL, from ``.gitmodules`` in HEAD."""
    text = _show(root, ".gitmodules") or ""
    paths, urls = {}, {}
    name = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[submodule"):
            name = line.split('"')[1]
        elif "=" in line:
            key, value = (part.strip() for part in line.split("=", 1))
            if key == "path":
                paths[name] = value
            elif key == "url":
                urls[name] = value
    return {path: urls[name] for name, path in paths.items() if name in urls}


def _pointer(root: Path, path: str) -> str | None:
    """The commit HEAD records for the submodule at ``path``; ``None`` if none."""
    entry = _git("ls-tree", "HEAD", "--", path, root=root)
    if not entry:
        return None
    mode, _, sha = entry.split("\t")[0].split()
    return sha if mode == "160000" else None


def _exact_pins(lines: list[str]) -> dict[str, Version | None]:
    """canvodpy package -> its exact ``==`` version (``None`` if not exact)."""
    pins = {}
    for line in lines:
        req = Requirement(line)
        if req.name.startswith("canvod"):
            exact = [s.version for s in req.specifier if s.operator == "=="]
            pins[req.name] = Version(exact[0]) if exact else None
    return pins


def _header_pins(text: str) -> dict[str, Version | None] | None:
    """The canvodpy pins of a notebook's script header; ``None`` without a header.

    Raises ``ValueError`` when the header is no valid TOML.
    """
    header = HEADER.search(text)
    if header is None:
        return None
    body = "\n".join(
        line.removeprefix("#").strip() for line in header["body"].splitlines()
    )
    try:
        return _exact_pins(tomllib.loads(body).get("dependencies", []))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"unreadable script header ({error})") from None


def _needed_increment(message: str) -> int:
    """The increment one commit calls for: breaking major, feature or deprecation minor.

    ``message`` is the whole commit message: a ``BREAKING CHANGE:`` footer
    counts. A deprecation is a commit whose description starts with
    "deprecate", as the deprecation commits are written.
    """
    subject = message.splitlines()[0] if message else ""
    match = SUBJECT.match(subject)
    kind = match["type"] if match else ""
    if (match and match["bang"]) or BREAKING.search(message):
        return 2
    deprecation = bool(match and DEPRECATION.match(match["text"]))
    if kind == "feat" or (kind not in NO_BEHAVIOR and deprecation):
        return 1
    return 0


def _messages(root: Path, revisions: str) -> list[tuple[str, str]]:
    """(short hash, whole message) of the non-merge commits in ``revisions``."""
    out = _git("log", "--no-merges", "--format=%h%x00%B%x1e", revisions, root=root)
    commits = []
    for record in out.split("\x1e"):
        short, _, message = record.strip().partition("\x00")
        if short:
            commits.append((short, message.strip()))
    return commits


def _notable(message: str) -> bool:
    """Whether a release notebook may have to describe the commit."""
    match = SUBJECT.match(message.splitlines()[0] if message else "")
    return bool(match and match["type"] in NOTABLE) or _needed_increment(message) > 0


def _check_main(head: str, remote: Remote, origin: str) -> Check:
    main = remote.main_head(origin)
    if head != main:
        return Check(
            FAIL,
            f"HEAD {head[:9]} is not main on GitHub ({(main or 'none')[:9]}): "
            "release from an up-to-date main (git switch main && git pull).",
        )
    return Check(PASS, f"HEAD is main on GitHub ({head[:9]})")


def _check_ci(head: str, remote: Remote) -> Check:
    state = remote.ci(head)
    if state == CI_PASSED:
        return Check(PASS, "CI passed on HEAD (it includes just check-release-notes)")
    reasons = {
        CI_RUNNING: "is still running",
        CI_FAILED: "failed",
        CI_NONE: "has no runs",
    }
    return Check(
        FAIL,
        f"CI {reasons[state]} on HEAD {head[:9]}: release only a commit whose checks passed.",
    )


def _check_refusals(
    packages: dict[str, Package], root: Path, new: Version
) -> list[Check]:
    """What ``prepare`` would refuse for canvodpy ``new``, before it runs."""
    problems = _refusals(packages, {UMBRELLA: new}, root)
    if problems:
        return [Check(FAIL, problem) for problem in problems]
    return [
        Check(
            PASS,
            f"canvodpy {packages[UMBRELLA].version} -> {new}: version, tag, branch, "
            "citation files, ranges and release files as just release wants them",
        )
    ]


def _check_increment(root: Path, last: Version | None, new: Version) -> Check:
    if last is None:
        return Check(WARN, "No earlier release tag: the increment is not checked.")
    needed, why = 0, []
    for short, message in _messages(root, f"v{last}..HEAD"):
        step = _needed_increment(message)
        if step > needed:
            needed, why = step, []
        if step == needed and step > 0:
            why.append(f"{short} {message.splitlines()[0]}")
    chosen = _increment(last, new)
    if chosen < needed:
        shown = "; ".join(why[:3]) + (
            f"; and {len(why) - 3} more" if len(why) > 3 else ""
        )
        return Check(
            FAIL,
            f"{new} is a {KINDS[chosen]} release, but the commits since v{last} "
            f"call for a {KINDS[needed]}: {shown}",
        )
    return Check(
        PASS,
        f"{KINDS[chosen]} release; the commits since v{last} call for a {KINDS[needed]}",
    )


def _check_pointer(root: Path, remote: Remote, path: str, url: str | None) -> Check:
    pointer = _pointer(root, path)
    if pointer is None or url is None:
        return Check(FAIL, f"{path} is not a submodule in HEAD and .gitmodules.")
    main = remote.main_head(url)
    if pointer != main:
        return Check(
            FAIL,
            f"{path} points at {pointer[:9]}, its main is {(main or 'none')[:9]}: "
            "move the pointer in a pull request.",
        )
    return Check(PASS, f"{path} points at its main ({pointer[:9]})")


def _check_test_data_tag(root: Path, remote: Remote, url: str | None) -> Check:
    pointer = _pointer(root, TEST_DATA)
    if pointer is None or url is None:
        return Check(FAIL, f"{TEST_DATA} is not a submodule in HEAD and .gitmodules.")
    tags = remote.tags_at(url, pointer)
    if not tags:
        return Check(
            FAIL,
            f"The test-data commit {pointer[:9]} has no tag: release the test "
            "data first (tag it in canvodpy-test-data and make a GitHub release; "
            "RELEASING.md, Test data).",
        )
    return Check(PASS, f"The test data is tagged {', '.join(tags)}")


def _expected_pins(root: Path, last: Version) -> dict[str, Version | None] | None:
    """canvodpy and the package versions it pinned in release ``last``, or
    None if the tag has no readable canvodpy/pyproject.toml."""
    text = _show(root, "canvodpy/pyproject.toml", f"v{last}")
    try:
        dependencies = tomllib.loads(text or "")["project"]["dependencies"]
    except tomllib.TOMLDecodeError, KeyError:
        return None
    pins = _exact_pins(dependencies)
    return {UMBRELLA: last, **pins}


def _demo_header_problems(
    demo: Path, pointer: str, expected: dict[str, Version | None]
) -> list[str]:
    """The demo notebooks whose canvodpy pins are not ``expected``."""
    problems = []
    names = _git("ls-tree", "--name-only", pointer, root=demo).splitlines()
    for name in sorted(n for n in names if n.endswith(".py")):
        text = _show(demo, name, pointer) or ""
        if "marimo.App(" not in text:
            continue
        try:
            pins = _header_pins(text)
        except ValueError as error:
            problems.append(f"{name} has an {error}")
            continue
        if not pins or UMBRELLA not in pins:
            problems.append(f"{name} pins no canvodpy")
            continue
        wrong = [
            f"{pkg}=={pin or '(no exact version)'}"
            for pkg, pin in sorted(pins.items())
            if pin is None or pin != expected.get(pkg)
        ]
        if wrong:
            problems.append(f"{name} pins {', '.join(wrong)}")
    return problems


def _check_demo_headers(root: Path, last: Version | None) -> Check:
    """Every demo notebook pins the last release: canvodpy and its packages."""
    if last is None:
        return Check(WARN, "No earlier release tag: the demo headers are not checked.")
    demo = root / DEMO
    pointer = _pointer(root, DEMO)
    if pointer is None:
        return Check(FAIL, f"{DEMO} is not a submodule in HEAD.")
    present = (demo / ".git").exists() and not subprocess.run(
        ["git", "cat-file", "-e", f"{pointer}^{{commit}}"],
        cwd=demo,
        capture_output=True,
    ).returncode
    if not present:
        return Check(
            FAIL,
            f"The demo submodule lacks commit {pointer[:9]}: git submodule update --init {DEMO}",
        )
    expected = _expected_pins(root, last)
    if expected is None:
        return Check(
            FAIL,
            f"v{last} has no readable canvodpy/pyproject.toml: the demo pins can't be compared.",
        )
    problems = _demo_header_problems(demo, pointer, expected)
    if problems:
        return Check(
            FAIL,
            f"Demo notebooks must pin the last release (canvodpy=={last} and its pins): "
            + "; ".join(problems),
        )
    return Check(PASS, f"Every demo notebook pins canvodpy=={last} and its pins")


def _check_release_notebook(root: Path, new: Version) -> list[Check]:
    """The release notebook of a minor or major release, on HEAD and linked."""
    path = f"release-notes/v{new}.py"
    text = _show(root, path)
    if text is None:
        return [
            Check(
                FAIL,
                f"{path} is not on HEAD: write it from release-notes/_template.py "
                "and merge it first.",
            )
        ]
    try:
        pinned = (_header_pins(text) or {}).get(UMBRELLA)
    except ValueError as error:
        pinned, checks = None, [Check(FAIL, f"{path} has an {error}.")]
    else:
        checks = []
    if pinned != new:
        checks.append(
            Check(FAIL, f"{path} pins canvodpy {pinned or '(nothing)'}, not =={new}.")
        )
    else:
        checks.append(Check(PASS, f"{path} pins canvodpy=={new}"))
    for listing, needle in (
        ("release-notes/README.md", f"v{new}.py"),
        ("docs/whats-new.md", path),
    ):
        if needle in (_show(root, listing) or ""):
            checks.append(Check(PASS, f"{listing} links the notebook"))
        else:
            checks.append(
                Check(FAIL, f"{listing} on HEAD does not link the notebook ({needle}).")
            )
    return checks


#: The docs template whose announce block is the banner on every docs page.
BANNER = "overrides/main.html"
ANNOUNCE = re.compile(r"(?s)\{% block announce %\}(?P<text>.*?)\{% endblock %\}")


def _check_banner(root: Path, new: Version) -> Check:
    """The docs banner of a minor or major release names it."""
    if new.is_prerelease:
        return Check(PASS, f"Pre-release: the docs banner ({BANNER}) is not checked")
    match = ANNOUNCE.search(_show(root, BANNER) or "")
    if match is None:
        return Check(PASS, f"{BANNER} has no banner")
    if re.search(rf"\bv{re.escape(str(new))}\b", match["text"]):
        return Check(PASS, f"The docs banner ({BANNER}) names v{new}")
    return Check(
        FAIL,
        f"The docs banner ({BANNER}, block announce) on HEAD doesn't name v{new}: "
        "change it in a pull request.",
    )


def _notable_pull_requests(root: Path, last: Version) -> list[str]:
    """``#number subject`` of the merged pull requests since ``last`` with a
    feature, fix or deprecation, merged or squashed."""
    out = _git(
        "log",
        "--first-parent",
        "--format=%H%x00%P%x00%cn%x00%s",
        f"v{last}..HEAD",
        root=root,
    )
    found = []
    for line in out.splitlines():
        sha, parents, committer, subject = line.split("\x00")
        merged = MERGED_PR.match(subject)
        squashed = SQUASHED_PR.search(subject)
        if merged and len(parents.split()) == 2:
            number, label = merged["number"], merged["branch"]
            messages = [m for _, m in _messages(root, f"{sha}^1..{sha}^2")]
        elif squashed and committer == GITHUB_COMMITTER:
            number, label = squashed["number"], subject[: squashed.start()]
            messages = [m for _, m in _messages(root, f"{sha}^..{sha}")]
        else:
            continue
        pr = f"#{number} {label}"
        if pr not in found and any(_notable(message) for message in messages):
            found.append(pr)
    return found


def _check_merged_prs(root: Path, last: Version | None, new: Version) -> Check:
    """A reminder: the notable pull requests the release notebook doesn't name."""
    if last is None:
        return Check(PASS, "No earlier release tag: no pull requests to compare")
    text = _show(root, f"release-notes/v{new}.py") or ""
    missing = [
        pr
        for pr in _notable_pull_requests(root, last)
        if not re.search(rf"{pr.split()[0]}\b", text)
    ]
    if missing:
        return Check(
            WARN,
            f"Pull requests since v{last} with a feature, fix or deprecation that the "
            "notebook doesn't name; check it covers the ones users notice: "
            + ", ".join(missing),
        )
    return Check(PASS, f"The notebook names every notable pull request since v{last}")


def check(version: str, root: Path = ROOT, remote: Remote | None = None) -> int:
    """Run every check, print one line each, return 1 if any failed."""
    if not RELEASE_VERSION.fullmatch(version):
        print(f"'{version}' is not a version (expected e.g. 1.1.0, no 'v').")
        return 2
    new = Version(version)
    origin = _git("remote", "get-url", "origin", root=root)
    remote = remote or GitHubRemote.from_origin(origin)
    urls = _submodule_urls(root)
    packages = _packages(root)
    last = _last_final(packages[UMBRELLA], root)
    head = _git("rev-parse", "HEAD", root=root)
    on_main = _check_main(head, remote, origin)
    checks = [
        on_main,
        # GitHub has CI runs only for pushed commits: ask once HEAD is main.
        _check_ci(head, remote)
        if on_main.status == PASS
        else Check(WARN, "CI is not checked: HEAD is not main."),
        *_check_refusals(packages, root, new),
        _check_increment(root, last, new),
        _check_pointer(root, remote, TEST_DATA, urls.get(TEST_DATA)),
        _check_test_data_tag(root, remote, urls.get(TEST_DATA)),
        _check_pointer(root, remote, DEMO, urls.get(DEMO)),
        _check_demo_headers(root, last),
    ]
    if last is None or _increment(last, new) > 0:
        checks += _check_release_notebook(root, new)
        checks.append(_check_banner(root, new))
        checks.append(_check_merged_prs(root, last, new))
    else:
        checks.append(Check(PASS, "Patch release: no release notebook needed"))
    for result in checks:
        print(f"{result.status} {result.text}")
    failed = sum(result.status == FAIL for result in checks)
    print(
        f"\n{failed} check(s) failed."
        if failed
        else "\nReady for `just release` (docs/RELEASING.md)."
    )
    return 1 if failed else 0


def main(argv: list[str], root: Path = ROOT, remote: Remote | None = None) -> int:
    if argv[:1] == ["check"] and len(argv) == 2:
        return check(argv[1], root=root, remote=remote)
    packages = _packages(root)
    if argv[:1] == ["status"]:
        return status(packages)
    if argv[:1] == ["prepare"] and len(argv) > 1:
        return prepare(packages, argv[1:])
    if argv == ["tag"]:
        return tag(packages, root)
    if argv == ["push"]:
        return push(packages, root)
    if argv == ["tagged"]:
        return tagged(packages, root)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
