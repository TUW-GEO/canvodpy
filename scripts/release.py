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
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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


def _git(*args: str, root: Path = ROOT) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
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


def _last_final(pkg: Package) -> Version | None:
    """The package's newest final (not pre-release) version among its tags.

    Like ``_last_tag``, a package without a final tag of its own falls back to
    the canvodpy tags.
    """
    for prefix in (pkg.tag(""), "v"):
        tags = _git("tag", "--merged", "HEAD", "--list", f"{prefix}*")
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


def _increment_from_final(pkg: Package, new: Version) -> int:
    """The increment of ``new`` over the package's last final version.

    From a pre-release (``1.0.0b1``) to its final (``1.0.0``) the release
    numbers don't change, so the increment counts from the version before.
    """
    old = pkg.version
    if old.is_prerelease:
        old = _last_final(pkg) or old
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


def _push_commands(tags: list[str]) -> list[str]:
    """The pushes for the release tags: canvodpy's tag on its own, first.

    GitHub creates no push event for tags when more than three tags are
    pushed at once, so a canvodpy tag pushed with the package tags never
    starts the workflow that drafts its GitHub release.
    """
    # canvodpy's tags are "v<version>", the packages' "<name>-v<version>".
    umbrella = [name for name in tags if name[:1] == "v" and name[1:2].isdigit()]
    others = [name for name in tags if name not in umbrella]
    return [
        f"git push origin {' '.join(group)}" for group in (umbrella, others) if group
    ]


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
    for name, new in chosen.items():
        old = packages[name].version
        if new <= old:
            problems.append(f"{name}: {new} is not above the current {old}.")
        if _git("tag", "--list", packages[name].tag(new)):
            problems.append(f"{name}: tag {packages[name].tag(new)} exists already.")
    if UMBRELLA in chosen and not problems:
        umbrella_step = _increment_from_final(packages[UMBRELLA], chosen[UMBRELLA])
        for name, new in chosen.items():
            step = _increment_from_final(packages[name], new)
            if step > umbrella_step:
                kinds = ("patch", "minor", "major")
                problems.append(
                    f"{name} makes a {kinds[step]} release, canvodpy only a {kinds[umbrella_step]}: "
                    "canvodpy's increment must be at least the largest one of its packages."
                )
    problems += _range_problems(packages, chosen)
    if UMBRELLA in chosen and _branch_taken(f"release/v{chosen[UMBRELLA]}"):
        problems.append(
            f"The branch release/v{chosen[UMBRELLA]} exists already (locally or on a "
            "remote, as of your last `git fetch`); the release commit goes on a new "
            "branch of that name. Delete the old branch first."
        )
    problems += [
        f"{problem} Zenodo reads the version from it; add it before releasing."
        for problem in _missing_citation_fields()
    ]
    dirty = _git(
        "status",
        "--porcelain",
        "--",
        *[str(f.relative_to(ROOT)) for f in _release_files(packages)],
    )
    if dirty:
        problems.append(
            f"Release files have uncommitted changes; commit or discard them first:\n{dirty}"
        )
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
    for command in _push_commands(tags):
        print(f"       {command}")
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


def tag(packages: dict[str, Package]) -> int:
    if _git("status", "--porcelain", "--untracked-files=no"):
        print("The working tree has uncommitted changes; tag a clean checkout of main.")
        return 1
    created = []
    for pkg in packages.values():
        name = pkg.tag(pkg.version)
        if _git("tag", "--list", name):
            continue
        _git("tag", "-a", name, "-m", f"Release {pkg.name} {pkg.version}")
        created.append(name)
    if not created:
        print("Every package version is tagged already.")
        return 0
    print("Created (not pushed):")
    for name in created:
        print(f"  {name}")
    print("\nPush them, canvodpy's tag on its own:")
    for command in _push_commands(created):
        print(f"  {command}")
    return 0


def tagged(packages: dict[str, Package]) -> int:
    """Print the packages whose release tag points at HEAD (for publishing)."""
    head = _git("rev-parse", "HEAD")
    names = []
    for pkg in packages.values():
        tag_name = pkg.tag(pkg.version)
        if (
            _git("tag", "--list", tag_name)
            and _git("rev-list", "-n", "1", tag_name) == head
        ):
            names.append(pkg.name)
    if not names:
        print("No package's release tag points at this commit.", file=sys.stderr)
        return 1
    print(" ".join(names))
    return 0


# ---------------------------------------------------------------------------
# check: is the repository ready for ``prepare``? (docs/RELEASING.md)
# ---------------------------------------------------------------------------

PASS, WARN, FAIL = "✓", "⚠", "✗"
DEMO = "demo"
TEST_DATA = "packages/canvod-readers/tests/test_data"
KINDS = ("patch", "minor", "major")
DEPRECATION = re.compile(r"\bdeprecat", re.IGNORECASE)
#: Commit types that change no behaviour, so they never call for a minor.
NO_BEHAVIOUR = {"docs", "test", "ci", "chore", "build", "style"}
MERGED_PR = re.compile(
    r"^Merge pull request #(?P<number>\d+) from [^/]+/(?P<branch>\S+)"
)
RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")
HEADER = re.compile(r"(?ms)^# /// script\n(?P<body>.*?)^# ///$")


@dataclass
class Check:
    status: str
    text: str


class Remote(Protocol):
    """What only GitHub knows. ``GitHubRemote`` asks it; tests pass a fake."""

    def main_head(self, url: str) -> str | None:
        """The commit ``main`` of the repository at ``url`` points at."""
        ...

    def tags_at(self, url: str, sha: str) -> list[str]:
        """The tags of the repository at ``url`` that point at ``sha``."""
        ...

    def ci(self, sha: str) -> str:
        """CI of canvodpy's commit ``sha``: success, failure, pending or none."""
        ...


class GitHubRemote:
    """The remote through ``git ls-remote`` and the ``gh`` command line."""

    def __init__(self, repository: str) -> None:
        self.repository = repository  # owner/name of canvodpy on GitHub

    def _ls_remote(self, *args: str) -> list[tuple[str, str]]:
        result = subprocess.run(
            ["git", "ls-remote", *args], capture_output=True, text=True, check=True
        )
        return [
            tuple(line.split("\t", 1)) for line in result.stdout.splitlines() if line
        ]

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
        result = subprocess.run(
            [
                "gh",
                "api",
                "--paginate",
                f"repos/{self.repository}/commits/{sha}/check-runs",
                "--jq",
                ".check_runs[] | [.status, .conclusion] | @tsv",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        runs = [line.split("\t") for line in result.stdout.splitlines() if line]
        if not runs:
            return "none"
        if any(status != "completed" for status, _ in runs):
            return "pending"
        passed = {"success", "skipped", "neutral"}
        return "success" if all(c in passed for _, c in runs) else "failure"


def _submodule_urls(root: Path) -> dict[str, str]:
    """Submodule path -> URL, from ``.gitmodules``."""
    out = _git(
        "config",
        "--file",
        ".gitmodules",
        "--get-regexp",
        r"^submodule\..*\.(path|url)$",
        root=root,
    )
    paths, urls = {}, {}
    for line in out.splitlines():
        key, value = line.split(" ", 1)
        name, _, kind = key.removeprefix("submodule.").rpartition(".")
        (paths if kind == "path" else urls)[name] = value
    return {path: urls[name] for name, path in paths.items()}


def _pointer(root: Path, path: str) -> str:
    """The commit canvodpy's ``HEAD`` records for the submodule at ``path``."""
    mode, kind, sha = (
        _git("ls-tree", "HEAD", "--", path, root=root).split("\t")[0].split()
    )
    return sha


def _last_release(root: Path) -> Version | None:
    """canvodpy's newest final version among the ``v*`` tags reachable from HEAD."""
    versions = []
    for name in _git("tag", "--merged", "HEAD", "--list", "v*", root=root).splitlines():
        try:
            versions.append(Version(name.removeprefix("v")))
        except InvalidVersion:
            continue
    finals = [v for v in versions if not v.is_prerelease]
    return max(finals) if finals else None


def _needed_increment(subject: str) -> int:
    """The increment one commit calls for: breaking major, feature or deprecation minor."""
    match = SUBJECT.match(subject)
    kind = match["type"] if match else ""
    if (match and match["bang"]) or "BREAKING CHANGE" in subject:
        return 2
    if kind == "feat" or (kind not in NO_BEHAVIOUR and DEPRECATION.search(subject)):
        return 1
    return 0


def _header_pins(text: str) -> dict[str, str] | None:
    """Package -> exact version of the canvodpy pins in a notebook's script header.

    ``None`` when the notebook has no script header.
    """
    header = HEADER.search(text)
    if header is None:
        return None
    body = "\n".join(
        line.removeprefix("#").strip() for line in header["body"].splitlines()
    )
    deps = tomllib.loads(body).get("dependencies", [])
    pins = {}
    for line in deps:
        req = Requirement(line)
        if req.name.startswith("canvod"):
            exact = [s.version for s in req.specifier if s.operator == "=="]
            pins[req.name] = exact[0] if exact else str(req.specifier) or "(no version)"
    return pins


def _check_main(root: Path, remote: Remote, url: str) -> Check:
    head = _git("rev-parse", "HEAD", root=root)
    main = remote.main_head(url)
    if head != main:
        return Check(
            FAIL,
            f"HEAD {head[:9]} is not main on GitHub ({(main or 'none')[:9]}): release from an up-to-date main (git switch main && git pull).",
        )
    return Check(PASS, f"HEAD is main on GitHub ({head[:9]})")


def _check_ci(root: Path, remote: Remote) -> Check:
    head = _git("rev-parse", "HEAD", root=root)
    state = remote.ci(head)
    if state == "success":
        return Check(PASS, "CI passed on HEAD")
    reasons = {
        "pending": "is still running",
        "failure": "failed",
        "none": "has no runs",
    }
    return Check(
        FAIL,
        f"CI {reasons.get(state, state)} on HEAD {head[:9]}: release only a commit whose checks passed.",
    )


def _check_version(packages: dict[str, Package], root: Path, new: Version) -> Check:
    current = packages[UMBRELLA].version
    if new <= current:
        return Check(FAIL, f"canvodpy {new} is not above the current {current}.")
    if _git("tag", "--list", f"v{new}", root=root):
        return Check(FAIL, f"The tag v{new} exists already.")
    return Check(PASS, f"canvodpy {current} -> {new}")


def _check_increment(root: Path, last: Version | None, new: Version) -> Check:
    if last is None:
        return Check(WARN, "No earlier release tag: the increment is not checked.")
    commits = _git("log", "--no-merges", "--format=%h %s", f"v{last}..HEAD", root=root)
    needed, why = 0, []
    for line in commits.splitlines():
        short, _, subject = line.partition(" ")
        step = _needed_increment(subject)
        if step > needed:
            needed, why = step, []
        if step == needed and step > 0:
            why.append(f"{short} {subject}")
    chosen = _increment(last, new)
    if chosen < needed:
        shown = "; ".join(why[:3]) + (
            f"; and {len(why) - 3} more" if len(why) > 3 else ""
        )
        return Check(
            FAIL,
            f"{new} is a {KINDS[chosen]} release, but the commits since v{last} call for a {KINDS[needed]}: {shown}",
        )
    return Check(
        PASS,
        f"{KINDS[chosen]} release; the commits since v{last} call for a {KINDS[needed]}",
    )


def _check_branch(root: Path, new: Version) -> Check:
    branch = f"release/v{new}"
    if _branch_taken(branch, root=root):
        return Check(
            FAIL,
            f"The branch {branch} exists already (locally or on a remote, as of your last git fetch): delete it first.",
        )
    return Check(PASS, f"The branch {branch} is free")


def _check_release_files(packages: dict[str, Package], root: Path) -> Check:
    files = [str(f.relative_to(root)) for f in _release_files(packages, root)]
    dirty = _git("status", "--porcelain", "--", *files, root=root)
    if dirty:
        return Check(
            FAIL,
            "Release files have uncommitted changes: "
            + ", ".join(line.split(maxsplit=1)[-1] for line in dirty.splitlines()),
        )
    return Check(PASS, "No uncommitted changes in the release files")


def _check_pointer(root: Path, remote: Remote, path: str, url: str) -> Check:
    pointer = _pointer(root, path)
    main = remote.main_head(url)
    if pointer != main:
        return Check(
            FAIL,
            f"{path} points at {pointer[:9]}, its main is {(main or 'none')[:9]}: bump the pointer in a pull request.",
        )
    return Check(PASS, f"{path} points at its main ({pointer[:9]})")


def _check_test_data_tag(root: Path, remote: Remote, url: str) -> Check:
    pointer = _pointer(root, TEST_DATA)
    tags = remote.tags_at(url, pointer)
    if not tags:
        return Check(
            WARN,
            f"The test-data commit {pointer[:9]} has no tag: tag the test data this release is tested with.",
        )
    return Check(PASS, f"The test data is tagged {', '.join(tags)}")


def _check_demo_headers(root: Path, last: Version | None) -> Check:
    """Every demo notebook pins the last release: canvodpy and its packages."""
    if last is None:
        return Check(WARN, "No earlier release tag: the demo headers are not checked.")
    demo = root / DEMO
    pointer = _pointer(root, DEMO)
    if (
        not (demo / ".git").exists()
        or subprocess.run(
            ["git", "cat-file", "-e", f"{pointer}^{{commit}}"],
            cwd=demo,
            capture_output=True,
        ).returncode
    ):
        return Check(
            FAIL,
            f"The demo submodule lacks commit {pointer[:9]}: git submodule update --init {DEMO}",
        )
    pyproject = tomllib.loads(
        _git("show", f"v{last}:canvodpy/pyproject.toml", root=root)
    )
    expected = {UMBRELLA: str(last)}
    for line in pyproject["project"]["dependencies"]:
        req = Requirement(line)
        exact = [s.version for s in req.specifier if s.operator == "=="]
        if req.name.startswith("canvod") and exact:
            expected[req.name] = exact[0]
    problems = []
    names = _git("ls-tree", "--name-only", pointer, root=demo).splitlines()
    notebooks = [name for name in sorted(names) if name.endswith(".py")]
    for name in notebooks:
        text = _git("show", f"{pointer}:{name}", root=demo)
        if "marimo.App(" not in text:
            continue
        pins = _header_pins(text)
        if not pins or UMBRELLA not in pins:
            problems.append(f"{name} pins no canvodpy")
            continue
        wrong = [
            f"{pkg}=={pin}"
            for pkg, pin in sorted(pins.items())
            if pin != expected.get(pkg)
        ]
        if wrong:
            problems.append(f"{name} pins {', '.join(wrong)}")
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
    shown = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=root, capture_output=True, text=True
    )
    if shown.returncode:
        return [
            Check(
                FAIL,
                f"{path} is not on HEAD: write it from release-notes/_template.py and merge it first.",
            )
        ]
    checks = []
    pins = _header_pins(shown.stdout) or {}
    if pins.get(UMBRELLA) != str(new):
        checks.append(
            Check(
                FAIL,
                f"{path} pins canvodpy {pins.get(UMBRELLA, '(nothing)')}, not =={new}.",
            )
        )
    else:
        checks.append(Check(PASS, f"{path} pins canvodpy=={new}"))
    for listing, needle in (
        ("release-notes/README.md", f"v{new}.py"),
        ("docs/whats-new.md", path),
    ):
        text = (root / listing).read_text() if (root / listing).exists() else ""
        if needle in text:
            checks.append(Check(PASS, f"{listing} links the notebook"))
        else:
            checks.append(
                Check(FAIL, f"{listing} does not link the notebook ({needle}).")
            )
    return checks


def _check_merged_prs(root: Path, last: Version | None, new: Version) -> Check:
    """A reminder: the feature and fix pull requests since the last release."""
    if last is None:
        return Check(PASS, "No earlier release tag: no pull requests to compare")
    notebook = root / f"release-notes/v{new}.py"
    text = notebook.read_text() if notebook.exists() else ""
    merges = _git(
        "log", "--merges", "--first-parent", "--format=%s", f"v{last}..HEAD", root=root
    )
    missing = []
    for subject in merges.splitlines():
        match = MERGED_PR.match(subject)
        if match and match["branch"].split("/")[0] in {"feat", "fix"}:
            if f"#{match['number']}" not in text:
                missing.append(f"#{match['number']} {match['branch']}")
    if missing:
        return Check(
            WARN,
            f"Pull requests since v{last} the notebook doesn't name; check it covers the ones users notice: "
            + ", ".join(missing),
        )
    return Check(
        PASS, f"The notebook names every feature and fix pull request since v{last}"
    )


def check(version: str, root: Path = ROOT, remote: Remote | None = None) -> int:
    """Run every check, print one line each, return 1 if any failed."""
    # The same form ``prepare`` takes: X.Y.Z, or a pre-release such as 1.2.0rc1.
    if not RELEASE_VERSION.fullmatch(version):
        print(f"'{version}' is not a version (expected e.g. 1.1.0, no 'v').")
        return 2
    new = Version(version)
    urls = _submodule_urls(root)
    origin = _git("remote", "get-url", "origin", root=root)
    if remote is None:
        repository = re.sub(r"^.*github\.com[:/]|\.git$", "", origin)
        remote = GitHubRemote(repository)
    packages = _packages(root)
    last = _last_release(root)
    checks = [
        _check_main(root, remote, origin),
        _check_ci(root, remote),
        _check_version(packages, root, new),
        _check_increment(root, last, new),
        _check_branch(root, new),
        _check_release_files(packages, root),
        _check_pointer(root, remote, TEST_DATA, urls[TEST_DATA]),
        _check_test_data_tag(root, remote, urls[TEST_DATA]),
        _check_pointer(root, remote, DEMO, urls[DEMO]),
        _check_demo_headers(root, last),
    ]
    if last is None or _increment(last, new) > 0:
        checks += _check_release_notebook(root, new)
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
    packages = _packages()
    if argv[:1] == ["status"]:
        return status(packages)
    if argv[:1] == ["prepare"] and len(argv) > 1:
        return prepare(packages, argv[1:])
    if argv == ["tag"]:
        return tag(packages)
    if argv == ["tagged"]:
        return tagged(packages)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
