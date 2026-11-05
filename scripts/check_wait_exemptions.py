# /// script
# requires-python = ">=3.14"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Check that the one-week-wait exemptions name the other repo's packages.

``uv lock`` takes only package files at least a week on PyPI
(``exclude-newer`` in ``pyproject.toml``), but the packages released from
canvodpy-extensions are taken right away. Their names are written by hand
in two places:

- ``pyproject.toml``: ``[tool.uv] exclude-newer-package``
- ``.github/dependabot.yml``: ``cooldown.exclude`` of the uv ecosystem

This check fails when the two lists differ from each other or from the
packages canvodpy-extensions releases (the ``name`` of each
``packages/*/pyproject.toml`` on its main branch, fetched with a shallow
``git clone``). canvodpy-extensions runs the same check the other way
round (scripts/check_wait_exemptions.py there).

Usage: ``uv run --script scripts/check_wait_exemptions.py``
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

#: The repo whose packages are exempt, and where its released packages are.
OTHER_REPO = "https://github.com/TUW-GEO/canvodpy-extensions.git"
OTHER_PYPROJECTS = ["packages/*/pyproject.toml"]


def released_packages() -> set[str]:
    """The names of the packages released from the other repo's main branch."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", OTHER_REPO, tmp],
            check=True,
        )
        return {
            tomllib.loads(path.read_text())["project"]["name"]
            for pattern in OTHER_PYPROJECTS
            for path in Path(tmp).glob(pattern)
        }


def pyproject_exemptions() -> set[str]:
    """The packages ``exclude-newer-package`` exempts from the wait."""
    uv = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]
    return {name for name, wait in uv["exclude-newer-package"].items() if not wait}


def dependabot_exemptions() -> set[str]:
    """The packages the uv ecosystem's cooldown excludes."""
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    (uv,) = [u for u in config["updates"] if u["package-ecosystem"] == "uv"]
    return set(uv["cooldown"]["exclude"])


def main() -> int:
    released = released_packages()
    if not released:
        print(f"No packages found in {OTHER_REPO}; check OTHER_PYPROJECTS.")
        return 1
    problems = []
    for where, names in (
        ("pyproject.toml exclude-newer-package", pyproject_exemptions()),
        (".github/dependabot.yml cooldown.exclude", dependabot_exemptions()),
    ):
        if missing := sorted(released - names):
            problems.append(f"{where} misses {', '.join(missing)}")
        if extra := sorted(names - released):
            problems.append(f"{where} names {', '.join(extra)}, not released")
    if problems:
        print(f"Packages released from {OTHER_REPO}: {', '.join(sorted(released))}")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print(f"Both lists name the {len(released)} released packages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
