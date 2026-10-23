"""The release script checks the ranges between packages before it writes.

Every package requires the others within a range. A package left out of a
release keeps its current version, so that version must fit the ranges too.
"""

from pathlib import Path

import pytest
from packaging.version import Version
from test_release_citation import release


def _package(root: Path, name: str, version: str, deps: list[str]):
    folder = root / name
    folder.mkdir()
    lines = ", ".join(f'"{dep}"' for dep in deps)
    (folder / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\ndependencies = [{lines}]\n'
    )
    return release.Package(name, folder)


@pytest.fixture
def packages(tmp_path: Path) -> dict:
    found = [
        _package(tmp_path, "canvod-utils", "0.4.0", []),
        _package(tmp_path, "canvod-store", "0.4.0", ["canvod-utils>=1.0.0,<2"]),
    ]
    return {pkg.name: pkg for pkg in found}


def test_releasing_both_packages_fits_the_range(packages: dict) -> None:
    chosen = {"canvod-utils": Version("1.0.0"), "canvod-store": Version("1.0.0")}
    assert release._range_problems(packages, chosen) == []


def test_a_package_left_out_of_the_release_is_named(packages: dict) -> None:
    problems = release._range_problems(packages, {"canvod-store": Version("1.0.0")})
    assert len(problems) == 1
    assert "excludes the current canvod-utils 0.4.0" in problems[0]


def test_a_chosen_version_outside_the_range_is_named(packages: dict) -> None:
    chosen = {"canvod-utils": Version("2.0.0"), "canvod-store": Version("2.0.0")}
    problems = release._range_problems(packages, chosen)
    assert len(problems) == 1
    assert "excludes canvod-utils 2.0.0" in problems[0]
