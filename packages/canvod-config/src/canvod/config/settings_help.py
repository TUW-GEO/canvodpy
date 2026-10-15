"""What each setting of ``canvod-settings.yaml`` means, from the models.

The descriptions on the pydantic models are the one source of the help
texts: ``canvodpy config explain``, the ``?`` answer of
``canvodpy config init --interactive``, the settings reference page
(``scripts/settings_docs.py``) and the links in the settings template all
come from here.

A setting is named by its path in the file, with a placeholder for the
names you choose: ``sites.<site>.receivers.<receiver>.directory``. An item
of a list is named with ``[]``: ``processing.references.funding[].funder``.
"""

from __future__ import annotations

import difflib
import json
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import annotated_types
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from canvod.config.models.root import CanvodConfig
from canvod.config.models.sites import SitesConfig

#: Where the settings reference page is published.
DOCS_URL = "https://canvodpy.eu/guides/settings/"

#: Settings reserved for later versions: no run reads them, so they are
#: left out of the help and the reference page.
_RESERVED = frozenset(
    {
        "processing.storage.statistics_store_name",
        "processing.storage.rollup_store_name",
        "processing.preprocessing.statistics",
    }
)

#: The placeholder of each mapping whose keys you name.
_PLACEHOLDERS = {
    "sites": "<site>",
    "receivers": "<receiver>",
    "vod_analyses": "<analysis>",
}


@dataclass(frozen=True)
class SettingHelp:
    """One setting, or one section of settings, and what it means.

    ``default`` is the value as written in the file (``null`` for none);
    it is ``None`` when the setting has to be set, and for a section.
    """

    path: str
    description: str
    kind: str
    default: str | None
    limits: tuple[str, ...]
    section: bool

    @property
    def anchor(self) -> str:
        """The anchor of the setting on the reference page."""
        return anchor(self.path)

    @property
    def docs_url(self) -> str:
        """The setting on the reference page."""
        return DOCS_URL + "#" + self.anchor


def anchor(path: str) -> str:
    """The anchor of *path* on the reference page."""
    for char in "<>[]":
        path = path.replace(char, "")
    return path.replace(".", "-")


def _models(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for arg in typing.get_args(annotation):
        found += _models(arg)
    return found


def _container(annotation: Any) -> Literal["dict", "list"] | None:
    """Whether *annotation* is a mapping or a list of models."""
    for option in (annotation, *typing.get_args(annotation)):
        origin = typing.get_origin(option)
        if origin is dict and _models(option):
            return "dict"
        if origin is list and _models(option):
            return "list"
    return None


_KINDS: dict[Any, str] = {
    str: "text",
    int: "whole number",
    float: "number",
    bool: "true or false",
    Path: "path",
    dict: "mapping",
}


def _kind(annotation: Any) -> str:
    """The type of a setting, in words."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is Literal:
        return "one of " + ", ".join(json.dumps(arg) for arg in args)
    if origin in (typing.Union, types.UnionType):
        options = [_kind(arg) for arg in args if arg is not type(None)]
        text = " or ".join(dict.fromkeys(options))
        return text + ", or null" if type(None) in args else text
    if origin is list:
        return "list of " + (_kind(args[0]) if args else "values")
    if origin is dict:
        return "mapping"
    if getattr(annotation, "__name__", "") == "EmailStr":
        return "email address"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "section"
    return _KINDS.get(annotation, getattr(annotation, "__name__", str(annotation)))


def _yaml(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value) if value == "" or ":" in value else value
    return json.dumps(value)


def _default(field: FieldInfo, parent: BaseModel | None, name: str) -> str | None:
    if parent is not None:
        # A section with a default (e.g. the chunks of the GNSS store) sets
        # the defaults of its settings.
        return _yaml(getattr(parent, name))
    if field.is_required():
        return None
    value = field.get_default(call_default_factory=True, validated_data={})
    return None if isinstance(value, BaseModel) else _yaml(value)


_LIMITS = {
    annotated_types.Ge: ("ge", ">="),
    annotated_types.Gt: ("gt", ">"),
    annotated_types.Le: ("le", "<="),
    annotated_types.Lt: ("lt", "<"),
    annotated_types.MinLen: ("min_length", "at least {} items"),
    annotated_types.MaxLen: ("max_length", "at most {} items"),
}


def _limits(field: FieldInfo) -> tuple[str, ...]:
    found = []
    for item in field.metadata:
        for cls, (attr, text) in _LIMITS.items():
            if isinstance(item, cls):
                value = getattr(item, attr)
                found.append(text.format(value) if "{}" in text else f"{text} {value}")
    return tuple(found)


def _section_default(field: FieldInfo) -> BaseModel | None:
    if field.default_factory is None:
        return None
    try:
        value = field.get_default(call_default_factory=True, validated_data={})
    except ValidationError:
        return None  # the section has settings you have to set
    return value if isinstance(value, BaseModel) else None


def _walk(
    model: type[BaseModel], prefix: str, parent: BaseModel | None = None
) -> list[SettingHelp]:
    found: list[SettingHelp] = []
    for name, field in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        if path in _RESERVED:
            continue
        models = _models(field.annotation)
        container = _container(field.annotation)
        if model is SitesConfig and name == "sites":
            # The file names its sites directly under `sites:`.
            path = f"{prefix}.{_PLACEHOLDERS['sites']}"
            container = None
        found.append(
            SettingHelp(
                path=path,
                description=field.description or "",
                kind="section" if models else _kind(field.annotation),
                default=None if models else _default(field, parent, name),
                limits=_limits(field),
                section=bool(models),
            )
        )
        if not models:
            continue
        if container == "dict":
            child = f"{path}.{_PLACEHOLDERS[name]}"
        elif container == "list":
            child = f"{path}[]"
        else:
            child = path
        found += _walk(models[0], child, _section_default(field))
    return found


def all_settings() -> list[SettingHelp]:
    """Every setting and section, in the order of the models."""
    return _walk(CanvodConfig, "")


class UnknownSettingError(KeyError):
    """No setting has the path asked for."""


def _matches(pattern: str, path: str) -> bool:
    want = [part.split("[")[0] for part in path.split(".")]
    have = [part.removesuffix("[]") for part in pattern.split(".")]
    if len(want) != len(have):
        return False
    return all(h.startswith("<") or h == w for h, w in zip(have, want, strict=True))


def _ends_with(pattern: str, path: str) -> bool:
    """Whether the end of *pattern*, from a named part on, matches *path*."""
    parts = pattern.split(".")
    return any(
        _matches(".".join(parts[i:]), path)
        for i in range(1, len(parts))
        if not parts[i].startswith("<")
    )


def find_setting(path: str) -> SettingHelp:
    """The setting at *path*, as written in the file or ending the path.

    ``sites.ExampleSite.receivers.canopy_01.directory`` finds
    ``sites.<site>.receivers.<receiver>.directory``, and ``gnss_store.epoch``
    finds ``processing.icechunk.chunk_strategies.gnss_store.epoch``.

    Raises
    ------
    UnknownSettingError
        If no setting, or more than one, ends with *path*; the message names
        the closest settings.
    """
    path = path.strip().strip(".")
    settings = all_settings()
    exact = [s for s in settings if _matches(s.path, path)]
    if exact:
        return exact[0]
    # A receiver or VOD analysis itself: its section of the site.
    named = [
        s
        for s in settings
        if s.section
        and any(t.path.startswith(f"{s.path}.<") for t in settings)
        and _matches(f"{s.path}.<name>", path)
    ]
    if named:
        return named[0]
    ending = [s for s in settings if _ends_with(s.path, path)]
    if len(ending) == 1:
        return ending[0]
    if ending:
        names = "\n  ".join(s.path for s in ending)
        msg = f"'{path}' names more than one setting:\n  {names}"
        raise UnknownSettingError(msg)
    # Compare with the same number of trailing parts, so a short name finds
    # its setting too.
    count = path.count(".") + 1
    endings: dict[str, str] = {}
    for setting in settings:
        endings.setdefault(".".join(setting.path.split(".")[-count:]), setting.path)
    close = [endings[e] for e in difflib.get_close_matches(path, endings, n=3)]
    msg = f"No setting '{path}'."
    if close:
        msg += " Did you mean:\n  " + "\n  ".join(close)
    raise UnknownSettingError(msg)


def children(section: SettingHelp) -> list[SettingHelp]:
    """The settings directly inside *section*."""
    inside = []
    for setting in all_settings():
        rest = setting.path.removeprefix(section.path).removeprefix("[]")
        if setting.path == section.path or not rest.startswith("."):
            continue
        parts = rest[1:].split(".")
        if parts[0].startswith("<"):
            parts = parts[1:]
        if len(parts) == 1:
            inside.append(setting)
    return inside


def explain(path: str) -> str:
    """What the setting at *path* means, as plain text.

    Raises
    ------
    UnknownSettingError
        If *path* names no setting (see :func:`find_setting`).
    """
    setting = find_setting(path)
    lines = [setting.path, "", setting.description or "(no description)", ""]
    if setting.section:
        lines.append("Settings in this section:")
        lines += [f"  {child.path.rsplit('.', 1)[-1]}" for child in children(setting)]
    else:
        lines.append(f"Type:    {setting.kind}")
        if setting.limits:
            lines.append(f"Limits:  {', '.join(setting.limits)}")
        default = (
            "none, you have to set it" if setting.default is None else setting.default
        )
        lines.append(f"Default: {default}")
    lines += ["", f"More: {setting.docs_url}"]
    return "\n".join(lines)
