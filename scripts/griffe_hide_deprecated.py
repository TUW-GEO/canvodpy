"""Griffe extension: leave deprecated code out of the API reference.

Code marked with the ``deprecated`` decorator of canvod-utils still ships
until the next major version, but the docs describe only the code to use.
The extension removes every class, function, method and property that
carries the decorator, and every re-export of one, from the loaded API.
It also removes each argument named by a ``deprecated_argument`` decorator
from its function's signature.

Configured in ``zensical.toml`` (mkdocstrings handler option ``extensions``).
"""

from __future__ import annotations

import ast
from typing import Any

import griffe


def _decorated_deprecated(node: Any) -> bool:
    # Read the decorators from the source: griffe turns a property into an
    # attribute and keeps no decorators for it.
    for decorator in getattr(node, "decorator_list", []):
        # The bare name, ``utils.deprecated`` or a call such as
        # ``deprecated("...")``.
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = ast.unparse(target)
        if name == "deprecated" or name.endswith(".deprecated"):
            return True
    return False


def _deprecated_arguments(node: Any) -> list[str]:
    # ``deprecated_argument("name", "message")``, bare or as an attribute.
    names = []
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        name = ast.unparse(decorator.func)
        first = decorator.args[0]
        if (
            name == "deprecated_argument" or name.endswith(".deprecated_argument")
        ) and isinstance(first, ast.Constant):
            names.append(first.value)
    return names


def _drop_aliases(obj: griffe.Object, removed: set[str]) -> None:
    for name, member in list(obj.members.items()):
        if isinstance(member, griffe.Alias):
            if member.target_path in removed:
                obj.del_member(name)
        elif member.is_module or member.is_class:
            _drop_aliases(member, removed)


class HideDeprecated(griffe.Extension):
    """Remove objects decorated with ``deprecated`` once a package is loaded."""

    def __init__(self) -> None:
        self._found: dict[str, griffe.Object] = {}

    def _check(self, node: Any, obj: griffe.Object) -> None:
        if _decorated_deprecated(node):
            self._found[obj.path] = obj

    def on_class_instance(self, *, node: Any, cls: griffe.Class, **kwargs: Any) -> None:
        self._check(node, cls)

    def on_function_instance(
        self, *, node: Any, func: griffe.Function, **kwargs: Any
    ) -> None:
        self._check(node, func)
        for name in _deprecated_arguments(node):
            del func.parameters[name]

    def on_attribute_instance(
        self, *, node: Any, attr: griffe.Attribute, **kwargs: Any
    ) -> None:
        self._check(node, attr)

    def on_package(self, *, pkg: griffe.Module, **kwargs: Any) -> None:
        mine = {
            path: obj
            for path, obj in self._found.items()
            if path == pkg.path or path.startswith(pkg.path + ".")
        }
        for obj in mine.values():
            if obj.parent is not None and obj.name in obj.parent.members:
                obj.parent.del_member(obj.name)
        _drop_aliases(pkg, set(mine))
