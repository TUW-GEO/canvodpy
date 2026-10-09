"""Check that every package imports with only its own declared dependencies.

For each package in ``packages/``, this installs the package with its
runtime dependencies alone (``uv run --frozen --isolated --package <name>
--no-dev``: no dev groups, no other workspace packages) and imports every
module of it. A module that fails names a dependency the package uses but
does not declare in its ``pyproject.toml`` (e.g. canvod-auxiliary imported
``rich`` while only the umbrella ``canvodpy`` declared it). In the
workspace ``.venv`` such a gap stays hidden, because the other packages
install everything.

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
failed = 0
for mod in pkgutil.walk_packages(pkg.__path__, sys.argv[1] + "."):
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


def main(argv: list[str]) -> int:
    packages = _packages()
    selected = argv or list(packages)
    unknown = [name for name in selected if name not in packages]
    if unknown:
        print(f"Unknown package(s): {', '.join(unknown)}")
        return 2

    failed = []
    for name in selected:
        result = subprocess.run(
            [
                "uv", "run", "--frozen", "--isolated", "--quiet",
                "--package", name, "--no-dev",
                "python", "-c", IMPORT_ALL, packages[name],
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
