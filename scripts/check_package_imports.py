"""Check that every package imports with only its own declared dependencies.

For each package in ``packages/``, this installs the package with its
runtime dependencies alone (``uv run --frozen --isolated --package <name>
--no-dev``: no dev groups, no other workspace packages) and imports every
module of it. A module that fails names a dependency the package uses but
does not declare in its ``pyproject.toml`` (e.g. canvod-auxiliary imported
``rich`` while only the umbrella ``canvodpy`` declared it). In the
workspace ``.venv`` such a gap stays hidden, because the other packages
install everything.

Optional extras are not installed by this check, so a submodule that an
optional extra provides (``canvod.viz.widgets`` behind the ``widgets``
extra) is skipped rather than reported as a missing declared dependency.

Usage: ``python scripts/check_package_imports.py [package ...]`` (default:
all packages). Exits non-zero if any module fails to import.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Runs inside the isolated environment: imports every module of one
#: namespace package and prints one line per failure.
IMPORT_ALL = """
import importlib, pkgutil, sys
try:
    pkg = importlib.import_module(sys.argv[1])
except Exception as exc:
    print(f"  {sys.argv[1]}: {type(exc).__name__}: {exc}")
    sys.exit(1)
excluded = sys.argv[2:]
failed = 0
for mod in pkgutil.walk_packages(pkg.__path__, sys.argv[1] + "."):
    if any(mod.name == prefix or mod.name.startswith(prefix + ".") for prefix in excluded):
        continue
    try:
        importlib.import_module(mod.name)
    except Exception as exc:
        failed += 1
        print(f"  {mod.name}: {type(exc).__name__}: {exc}")
sys.exit(1 if failed else 0)
"""


def _packages() -> dict[str, str]:
    """Return {distribution name: import name} for the packages in packages/."""
    found = {}
    for pyproject in sorted(ROOT.glob("packages/*/pyproject.toml")):
        name = tomllib.loads(pyproject.read_text())["project"]["name"]
        found[name] = "canvod." + name.removeprefix("canvod-").replace("-", "_")
    return found


def _optional_excludes(dist_name: str, import_name: str) -> list[str]:
    """Submodule prefixes behind a package's optional extras.

    An optional extra is not installed by this check (``--no-dev``), so a
    submodule it provides would fail to import on purpose. We skip any
    submodule named ``<import name>.<extra>`` (the extra name with ``-``
    mapped to ``_``), which matches e.g. the ``widgets`` extra of
    canvod-viz and its ``canvod.viz.widgets`` subpackage.
    """
    pyproject = ROOT / "packages" / dist_name / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    return [f"{import_name}.{extra.replace('-', '_')}" for extra in extras]


def main(argv: list[str]) -> int:
    packages = _packages()
    selected = argv or list(packages)
    unknown = [name for name in selected if name not in packages]
    if unknown:
        print(f"Unknown package(s): {', '.join(unknown)}")
        return 2

    failed = []
    for name in selected:
        import_name = packages[name]
        result = subprocess.run(
            [
                "uv", "run", "--frozen", "--isolated", "--quiet",
                "--package", name, "--no-dev",
                "python", "-c", IMPORT_ALL, import_name,
                *_optional_excludes(name, import_name),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )  # fmt: skip
        if result.returncode == 0:
            print(f"ok    {name}")
        else:
            failed.append(name)
            print(f"FAIL  {name}")
            print(result.stdout + result.stderr, end="")

    if failed:
        print(
            f"\n{len(failed)} package(s) use a dependency they do not declare: "
            f"{', '.join(failed)}. Add it to that package's pyproject.toml."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
