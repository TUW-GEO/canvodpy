"""The modules of canvodpy import each other one way only (#657).

An import cycle forces imports into functions to work at all, and hides
which module depends on which. Imports for type annotations only (under
``if TYPE_CHECKING:``) don't run and are not counted. Importing a module
also runs its package's ``__init__``; those edges are not in the graph.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _module_name(path: Path) -> str:
    name = ".".join(path.relative_to(SRC).with_suffix("").parts)
    return name.removesuffix(".__init__")


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imported(tree: ast.AST) -> set[str]:
    """Modules imported anywhere in ``tree``, except under TYPE_CHECKING."""
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.If) and _is_type_checking(node):
            for sub in node.orelse:
                names |= _imported(ast.Module(body=[sub], type_ignores=[]))
            continue
        if isinstance(node, ast.ImportFrom):
            # canvodpy imports by absolute names only; a relative import
            # would need the importing module's package to resolve.
            assert node.level == 0, f"relative import of {node.module!r}"
            if node.module:
                names.add(node.module)
                # ``from package import module`` imports that module.
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        names |= _imported(node)
    return names


def _graph() -> dict[str, set[str]]:
    modules = {_module_name(p): p for p in SRC.rglob("*.py")}
    return {
        name: {
            target
            for target in _imported(ast.parse(path.read_text(encoding="utf-8")))
            if target in modules and target != name
        }
        for name, path in modules.items()
    }


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """The strongly connected components with more than one module (Tarjan)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return found


def test_the_cycle_finder_finds_a_cycle():
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}}
    assert _cycles(graph) == [["a", "b", "c"]]


def test_type_checking_imports_are_not_counted():
    tree = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from canvodpy.api import Site\n"
        "def f():\n"
        "    from canvodpy.vod_phase import units\n"
    )
    assert _imported(tree) == {
        "typing",
        "typing.TYPE_CHECKING",
        "canvodpy.vod_phase",
        "canvodpy.vod_phase.units",
    }


def test_a_module_imported_from_its_package_is_counted():
    tree = ast.parse("from canvodpy.orchestrator import processor\n")
    assert "canvodpy.orchestrator.processor" in _imported(tree)


def test_canvodpy_has_no_import_cycle():
    assert _cycles(_graph()) == []
