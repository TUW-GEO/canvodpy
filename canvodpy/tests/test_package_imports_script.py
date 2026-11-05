"""The package import check finds imports inside function bodies (#129).

Importing a module does not run its functions, so a dependency used only
inside a function stays hidden from an import of every module
(canvod-readers used ``pymap3d`` in a method). The check reads those
imports from the source and imports them in the package's own
environment, unless they are optional.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "check_package_imports", ROOT / "scripts" / "check_package_imports.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

SOURCE = """
from typing import TYPE_CHECKING

import numpy

if TYPE_CHECKING:
    import pandas


def needs_it():
    import pymap3d
    from canvod.store.day_blocks import load_group
    from canvod.readers.base import validate_dataset
    import json


def optional():
    try:
        import healpy
    except ImportError as e:
        raise ImportError("uv add healpy") from e
    try:
        import psutil
    except Exception:
        pass
    if TYPE_CHECKING:
        import polars
"""


def test_only_required_imports_in_function_bodies_are_found(tmp_path: Path) -> None:
    package = tmp_path / "canvod" / "readers"
    package.mkdir(parents=True)
    (package / "geometry.py").write_text(SOURCE)
    optional = package / "widgets"
    optional.mkdir()
    (optional / "__init__.py").write_text("def show():\n    import ipywidgets\n")

    found = script.deferred_imports(
        tmp_path, "canvod.readers", ["canvod.readers.widgets"]
    )

    # Module-level imports, the package's own modules, the standard
    # library, guarded imports and optional extras are left out
    assert sorted(found) == ["canvod.store.day_blocks", "pymap3d"]
    assert found["pymap3d"].endswith("geometry.py:11")
