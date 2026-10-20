"""Every published package ships the repository's LICENSE and NOTICE.

Apache-2.0 asks that a copy of the license, and the NOTICE file, go with
every distribution. A package's ``license-files`` may only name files in
its own folder, so each package keeps a copy of both; the copies must not
drift from the files at the repository root.
"""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYPROJECTS = [
    ROOT / "canvodpy" / "pyproject.toml",
    *sorted(ROOT.glob("packages/*/pyproject.toml")),
]


@pytest.mark.parametrize("pyproject", PYPROJECTS, ids=lambda p: p.parent.name)
def test_package_declares_license(pyproject: Path) -> None:
    project = tomllib.loads(pyproject.read_text())["project"]
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE"]


@pytest.mark.parametrize("pyproject", PYPROJECTS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_license_copy_matches_root(pyproject: Path, name: str) -> None:
    copy = pyproject.parent / name
    assert copy.read_bytes() == (ROOT / name).read_bytes(), (
        f"{copy.relative_to(ROOT)} differs from {name} at the repository root; copy it again"
    )
