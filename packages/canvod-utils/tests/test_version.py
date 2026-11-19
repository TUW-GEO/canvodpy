"""The canvodpy version that a run names in its stores."""

from importlib.metadata import PackageNotFoundError, version

import pytest

from canvod.utils.tools import canvodpy_version, get_version_from_pyproject
from canvod.utils.tools import version as version_module


def test_canvodpy_version_is_the_installed_canvodpy():
    pytest.importorskip("canvodpy")
    assert canvodpy_version() == version("canvodpy")


def test_canvodpy_version_without_canvodpy_installed_is_unknown(monkeypatch):
    def not_installed(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(version_module, "_installed_version", not_installed)
    assert canvodpy_version() == "unknown"


def test_get_version_from_pyproject_is_deprecated_and_still_names_canvod_utils():
    with pytest.warns(FutureWarning, match="canvodpy_version"):
        assert get_version_from_pyproject() == version("canvod-utils")
