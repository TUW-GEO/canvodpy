# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Check that every package imports with only its own declared dependencies.

For each package in ``packages/``, this installs the package with its
runtime dependencies alone (``uv run --frozen --isolated --package <name>
--no-dev``: no dev groups, no other workspace packages) and imports every
module of it. A module that fails names a dependency the package uses but
does not declare in its ``pyproject.toml`` (e.g. canvod-auxiliary imported
``rich`` while only the umbrella ``canvodpy`` declared it). In the
workspace ``.venv`` such a gap stays hidden, because the other packages
install everything.

Importing a module does not run its functions, so an import inside a
function body stays hidden too (canvod-readers used ``pymap3d`` in a
method, #129). The check therefore also imports every module that a
function of the package imports, found in the source with ``ast``, except
imports guarded by ``try``/``except ImportError`` or ``TYPE_CHECKING``.
Last, it runs the ``## Example`` code of the package's README in the same
environment, from an empty folder. An example that needs input files (a
RINEX file, a store; ``EXAMPLE_NEEDS``) runs its import lines only, which
still finds an example that imports what the package doesn't install; the
part that reads the files is not checked. The other examples run in full,
so one that downloads would make the check need the network.

Optional extras are not installed by this check, so a submodule that an
optional extra provides (``canvod.viz.widgets`` behind the ``widgets``
extra) is skipped rather than reported as a missing declared dependency.

Usage: ``python scripts/check_package_imports.py [package ...]`` (default:
all packages). Exits non-zero if any module fails to import.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Runs inside the isolated environment: imports every module of one
#: namespace package and prints one line per failure.
IMPORT_ALL = """
import importlib, json, os, pkgutil, sys
try:
    pkg = importlib.import_module(sys.argv[1])
except Exception as exc:
    print(f"  {sys.argv[1]}: {type(exc).__name__}: {exc}")
    sys.exit(1)
excluded = sys.argv[2:]
failed = 0
for name, where in json.loads(os.environ.get("DEFERRED_IMPORTS", "{}")).items():
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed += 1
        print(f"  {name} (imported in {where}): {type(exc).__name__}: {exc}")
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


#: README examples that need input files CI doesn't have: only their
#: import lines run.
EXAMPLE_NEEDS = {
    "canvod-auxiliary": "an SP3 file",
    "canvod-config": "a settings file",
    "canvod-ops": "a RINEX file",
    "canvod-readers": "a RINEX file",
    "canvod-store": "a store",
    "canvod-store-metadata": "a store",
    "canvod-vod": "datasets read from a store",
}

#: Packages a README example tells its reader to install as well.
EXAMPLE_ALSO = {"canvod-ops": ["canvod-readers"]}


def readme_example(dist_name: str) -> str | None:
    """The first Python code block under ``## Example`` of a package's README."""
    readme = ROOT / "packages" / dist_name / "README.md"
    section = re.search(
        r"^## Example\n(.*?)(?=^## |\Z)", readme.read_text(), re.M | re.S
    )
    if section is None:
        return None
    block = re.search(r"^```python\n(.*?)^```", section.group(1), re.M | re.S)
    return block.group(1) if block else None


def import_lines(code: str) -> str:
    """The module-level import statements of *code*."""
    tree = ast.parse(code)
    return "\n".join(
        ast.unparse(node)
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )


def run_example(dist_name: str) -> str | None:
    """Run a package's README example in its isolated environment.

    Returns the end of the output if it fails, ``None`` if it runs.
    """
    code = readme_example(dist_name)
    if code is None:
        return "the README has no ## Example code block"
    if dist_name in EXAMPLE_NEEDS:
        code = import_lines(code)
    also = [
        arg
        for other in EXAMPLE_ALSO.get(dist_name, [])
        for arg in ("--with-editable", str(ROOT / "packages" / other))
    ]
    with tempfile.TemporaryDirectory() as folder:
        result = subprocess.run(
            [
                "uv", "run", "--project", str(ROOT), "--frozen", "--isolated",
                "--quiet", "--package", dist_name, "--no-dev", *also,
                "python", "-c", code,
            ],
            cwd=folder,
            capture_output=True,
            text=True,
            env={**os.environ, "MPLBACKEND": "Agg"},
        )  # fmt: skip
    if result.returncode == 0:
        return None
    return "\n".join((result.stdout + result.stderr).strip().splitlines()[-3:])


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


def _is_type_checking(test: ast.expr) -> bool:
    """``if TYPE_CHECKING`` or ``if typing.TYPE_CHECKING``, not its negation."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _guarded(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether an import is optional: in the ``try`` of a handler that
    catches ``ImportError`` (or ``ModuleNotFoundError``), or in the body of
    ``if TYPE_CHECKING``.

    A broader handler (``except Exception``, a bare ``except``) is no
    guard: it also hides a missing dependency without a word.
    """
    child, parent = node, parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.Try) and child in parent.body:
            for handler in parent.handlers:
                if handler.type is None:
                    continue
                names = (
                    handler.type.elts
                    if isinstance(handler.type, ast.Tuple)
                    else [handler.type]
                )
                if any(
                    isinstance(n, ast.Name)
                    and n.id in {"ImportError", "ModuleNotFoundError"}
                    for n in names
                ):
                    return True
        if (
            isinstance(parent, ast.If)
            and child in parent.body
            and _is_type_checking(parent.test)
        ):
            return True
        child, parent = parent, parents.get(parent)
    return False


def deferred_imports(
    source_dir: Path, import_name: str, excluded: list[str]
) -> dict[str, str]:
    """Modules imported inside function bodies, with where (first) found.

    Standard library modules, the package's own modules and guarded
    (optional) imports are left out, and so are modules of the
    ``excluded`` submodules (optional extras).
    """
    found: dict[str, str] = {}
    for path in sorted(source_dir.rglob("*.py")):
        module = ".".join(path.relative_to(source_dir).with_suffix("").parts)
        module = module.removesuffix(".__init__")
        if any(module == e or module.startswith(e + ".") for e in excluded):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif (
                    isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                ):
                    # canvod is a namespace package: ``from canvod import
                    # store`` imports the module canvod.store
                    names = (
                        [f"canvod.{alias.name}" for alias in node.names]
                        if node.module == "canvod"
                        else [node.module]
                    )
                else:
                    continue
                if _guarded(node, parents):
                    continue
                for name in names:
                    if name.split(".")[0] in sys.stdlib_module_names:
                        continue
                    if name == import_name or name.startswith(import_name + "."):
                        continue
                    where = f"{path.relative_to(source_dir)}:{node.lineno}"
                    found.setdefault(name, where)
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
        import_name = packages[name]
        excluded = _optional_excludes(name, import_name)
        deferred = deferred_imports(
            ROOT / "packages" / name / "src", import_name, excluded
        )
        result = subprocess.run(
            [
                "uv", "run", "--frozen", "--isolated", "--quiet",
                "--package", name, "--no-dev",
                "python", "-c", IMPORT_ALL, import_name,
                *excluded,
            ],
            cwd=ROOT,
            env={**os.environ, "DEFERRED_IMPORTS": json.dumps(deferred)},
            capture_output=True,
            text=True,
        )  # fmt: skip
        example_error = run_example(name)
        if result.returncode == 0 and example_error is None:
            what = " (example: imports only)" if name in EXAMPLE_NEEDS else ""
            print(f"ok    {name}{what}")
            continue
        failed.append(name)
        print(f"FAIL  {name}")
        if result.returncode != 0:
            print(result.stdout + result.stderr, end="")
        if example_error is not None:
            print(f"  README example: {example_error}")

    if failed:
        print(
            f"\n{len(failed)} package(s) fail: {', '.join(failed)}. A missing "
            f"module is a dependency to add to that package's pyproject.toml "
            f"(or to guard, if optional); a README example must run with what "
            f"its Install section installs."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
