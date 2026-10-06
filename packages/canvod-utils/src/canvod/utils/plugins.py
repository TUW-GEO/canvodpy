"""Plugins: readers and VOD calculators from installed packages.

A package adds a reader or a VOD calculator to ``canvodpy run`` by
declaring an entry point in its ``pyproject.toml``::

    [project.entry-points."canvodpy.readers"]
    my_format = "my_package.reader:MyFormatReader"

    [project.entry-points."canvodpy.vod_calculators"]
    my_model = "my_package.calculator:MyCalculator"

The entry point's name is the name used in the settings
(``reader_format``) and on the command line (``--vod-calculator``).
"""

from __future__ import annotations

import functools
from importlib.metadata import EntryPoint, entry_points

READER_GROUP = "canvodpy.readers"
VOD_CALCULATOR_GROUP = "canvodpy.vod_calculators"


class PluginError(RuntimeError):
    """An installed plugin cannot be used."""


def _package(ep: EntryPoint) -> str:
    """Name of the installed package that declares ``ep``."""
    return ep.dist.name if ep.dist is not None else ep.value


def _entry_points(group: str) -> dict[str, EntryPoint]:
    """Entry points of ``group`` by name; a name declared twice is an error."""
    found: dict[str, EntryPoint] = {}
    for ep in entry_points(group=group):
        if ep.name in found:
            raise PluginError(
                f"Two installed packages declare the {group} plugin "
                f"'{ep.name}': {_package(found[ep.name])} and {_package(ep)}. "
                "Uninstall one of them."
            )
        found[ep.name] = ep
    return found


def plugin_names(group: str) -> list[str]:
    """Names of the installed plugins of ``group``, without importing them."""
    return sorted(_entry_points(group))


@functools.cache
def load_plugins(group: str) -> dict[str, type]:
    """Import the installed plugins of ``group``.

    Returns
    -------
    dict[str, type]
        Plugin class by entry point name.

    Raises
    ------
    PluginError
        If a plugin cannot be imported or is not a class; the message names
        the package that declares it.
    """
    loaded: dict[str, type] = {}
    for name, ep in _entry_points(group).items():
        try:
            obj = ep.load()
        except Exception as exc:
            raise PluginError(
                f"The {group} plugin '{name}' of the package {_package(ep)} "
                f"cannot be imported ({ep.value}): {exc}. Fix or uninstall "
                f"{_package(ep)}."
            ) from exc
        if not isinstance(obj, type):
            raise PluginError(
                f"The {group} plugin '{name}' of the package {_package(ep)} "
                f"points to {ep.value}, which is not a class."
            )
        loaded[name] = obj
    return loaded


def plugin_package(group: str, name: str) -> str:
    """Name of the installed package that declares the plugin ``name``."""
    return _package(_entry_points(group)[name])
