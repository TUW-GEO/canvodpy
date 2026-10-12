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
        return (
            ROOT / "CHANGELOG.md"
            if self.name == UMBRELLA
            else self.folder / "CHANGELOG.md"
        )

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


def _packages() -> dict[str, Package]:
    found = {UMBRELLA: Package(UMBRELLA, ROOT / "canvodpy")}
    for pyproject in sorted(ROOT.glob("packages/*/pyproject.toml")):
        name = tomllib.loads(pyproject.read_text())["project"]["name"]
        found[name] = Package(name, pyproject.parent)
    return found


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"git {' '.join(args)} failed:\n{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


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


def _release_files(packages: dict[str, Package]) -> list[Path]:
    files = [ROOT / "pyproject.toml", ROOT / "uv.lock"]
    files += [ROOT / name for name in CITATION_FIELDS]
    for pkg in packages.values():
        files += [pkg.pyproject, pkg.changelog]
    return files


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
    for pkg in packages.values():
        if pkg.name == UMBRELLA:
            continue
        for req in pkg.requirements():
            if req.name in chosen and not req.specifier.contains(
                chosen[req.name], prereleases=True
            ):
                problems.append(
                    f"{pkg.name} requires {req}, which excludes {req.name} {chosen[req.name]}: "
                    f"check {pkg.name} against the new version and widen its range by hand."
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
    print(f"       git push origin {' '.join(tags)}")
    print("  4. GitHub Actions drafts the GitHub release of the canvodpy tag")
    print("  5. PyPI is separate and manual:")
    print(
        f"       gh workflow run publish_pypi.yml --ref {packages[UMBRELLA].tag(chosen[UMBRELLA])} "
        f"-f packages='{' '.join(chosen)}'"
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
    print(f"\nPush them: git push origin {' '.join(created)}")
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


def main(argv: list[str]) -> int:
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
