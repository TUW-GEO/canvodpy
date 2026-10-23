"""The core packages work without the canvodpy umbrella package.

canvodpy depends on the canvod-* packages, so none of them may import
canvodpy when it is imported: a standalone install of, e.g., canvod-store
would fail.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


def _module_level_canvodpy_imports(path: Path) -> list[int]:
    """Lines of ``path`` that import canvodpy outside a function or class."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                break
            names = (
                [a.name for a in sub.names]
                if isinstance(sub, ast.Import)
                else [sub.module or ""]
                if isinstance(sub, ast.ImportFrom)
                else []
            )
            if any(n == "canvodpy" or n.startswith("canvodpy.") for n in names):
                lines.append(sub.lineno)
    return lines


def test_no_core_package_imports_canvodpy_at_import_time() -> None:
    offenders = [
        f"{path.relative_to(PACKAGES)}:{line}"
        for path in sorted(PACKAGES.glob("*/src/**/*.py"))
        for line in _module_level_canvodpy_imports(path)
    ]
    assert not offenders, "canvodpy imported at module level:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    ("module", "name"), [("run_context", "get_run_id"), ("stage_timer", "stage_timer")]
)
def test_old_logging_module_paths_warn(module: str, name: str) -> None:
    old = importlib.import_module(f"canvodpy.logging.{module}")
    new = importlib.import_module(f"canvod.utils.logging.{module}")
    with pytest.warns(FutureWarning, match=f"canvod.utils.logging.{module}"):
        assert getattr(old, name) is getattr(new, name)


def test_one_run_id_for_both_paths() -> None:
    """canvodpy.logging re-exports the same run context, not a copy."""
    import canvodpy.logging as umbrella

    import canvod.utils.logging as shared

    assert umbrella.get_run_id is shared.get_run_id
    assert umbrella.stage_timer is shared.stage_timer


def test_get_logger_wrapper_warns() -> None:
    """Modules use ``structlog.get_logger``; the old wrapper still works."""
    import canvodpy.logging
    import structlog

    with pytest.warns(FutureWarning, match="structlog.get_logger"):
        log = canvodpy.logging.get_logger("canvodpy.test")
    assert type(log) is type(structlog.get_logger("canvodpy.test"))
