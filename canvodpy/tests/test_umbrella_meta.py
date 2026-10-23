"""Meta tests for canvodpy package."""

import importlib
import tomllib
from importlib.metadata import requires, version
from pathlib import Path

import pytest
from packaging.requirements import Requirement

PACKAGES = {
    "canvod-auxiliary": "canvod.auxiliary",
    "canvod-grids": "canvod.grids",
    "canvod-ops": "canvod.ops",
    "canvod-preflight": "canvod.preflight",
    "canvod-readers": "canvod.readers",
    "canvod-store": "canvod.store",
    "canvod-utils": "canvod.utils",
    "canvod-viz": "canvod.viz",
    "canvod-vod": "canvod.vod",
}


def test_package_imports():
    """Test that package can be imported."""
    import canvodpy

    assert canvodpy is not None
    assert canvodpy.__version__ is not None


@pytest.mark.parametrize("dist", sorted(PACKAGES))
def test_version_is_the_installed_one(dist):
    """``__version__`` comes from the installed package, never a hardcoded copy."""
    assert importlib.import_module(PACKAGES[dist]).__version__ == version(dist)


def test_canvodpy_pins_each_package_exactly():
    """A canvodpy version names exactly one tested mix of packages."""
    pins = {
        req.name: req.specifier
        for req in map(Requirement, requires("canvodpy") or [])
        if req.name.startswith("canvod-")
    }
    members = {
        tomllib.loads(p.read_text())["project"]["name"]
        for p in Path(__file__).parents[2].glob("packages/*/pyproject.toml")
    }
    assert set(pins) == members
    for name, specifier in pins.items():
        assert str(specifier) == f"=={version(name)}", name
