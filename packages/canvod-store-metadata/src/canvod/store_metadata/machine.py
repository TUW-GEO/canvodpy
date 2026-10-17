"""The settings that belong to one computer, not to a store.

Data roots and the cache and log folders differ from computer to computer
and often name a user. Stores are shared, so they never record them: the
settings recorded with each commit leave them out, and ``canvodpy config
init --from-store`` asks for them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The settings of one computer, as dotted keys; ``*`` stands for any site.
MACHINE_SETTINGS = (
    "sites.*.gnss_site_data_root",
    "processing.storage.aux_data_dir",
    "processing.storage.shared_aux_cache_dir",
    "processing.logging.log_dir",
)

#: The stores' root: a computer's setting when it is a local folder. An
#: ``s3://`` URL names the shared bucket and is kept.
STORES_ROOT_SETTING = "processing.storage.stores_root_dir"


def _paths(settings: Mapping[str, Any], key: str) -> list[tuple[str, ...]]:
    """The key paths of a dotted ``key``, ``*`` taken over the existing entries."""
    paths: list[tuple[str, ...]] = [()]
    for part in key.split("."):
        if part != "*":
            paths = [(*path, part) for path in paths]
            continue
        expanded = []
        for path in paths:
            node: Any = settings
            for step in path:
                node = node.get(step) if isinstance(node, Mapping) else None
            if isinstance(node, Mapping):
                expanded += [(*path, name) for name in node]
        paths = expanded
    return paths


def _is_local(root: Any) -> bool:
    """Whether the stores' root is a local folder (not an ``s3://`` URL)."""
    return root is not None and not str(root).startswith("s3://")


def without_machine_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of ``settings`` without the settings of one computer.

    Leaves out :data:`MACHINE_SETTINGS` and the stores' root when it is a
    local folder. ``settings`` is not changed.
    """
    keys = [*MACHINE_SETTINGS]
    storage = settings.get("processing", {}).get("storage", {})
    if isinstance(storage, Mapping) and _is_local(storage.get("stores_root_dir")):
        keys.append(STORES_ROOT_SETTING)
    result = _copy(settings)
    for key in keys:
        for path in _paths(result, key):
            parent: Any = result
            for step in path[:-1]:
                parent = parent.get(step) if isinstance(parent, dict) else None
            if isinstance(parent, dict):
                parent.pop(path[-1], None)
    return result


def set_machine_settings(settings: dict[str, Any], value: Any) -> None:
    """Set each of :data:`MACHINE_SETTINGS` in ``settings`` to ``value``.

    Creates the sections a setting needs; ``sites.*`` covers the sites
    ``settings`` already has.
    """
    for key in MACHINE_SETTINGS:
        for path in _paths(settings, key):
            parent = settings
            for step in path[:-1]:
                parent = parent.setdefault(step, {})
            parent[path[-1]] = value


def _copy(settings: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of nested mappings; other values are shared."""
    return {k: _copy(v) if isinstance(v, Mapping) else v for k, v in settings.items()}
