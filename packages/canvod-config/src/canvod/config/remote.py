"""The settings file read from a pinned URL.

``canvodpy -c URL`` (or ``CANVOD_CONFIG_DIR=URL``) reads the settings file
from a GitHub repository, pinned to a commit or a tag (the URL rules of
:mod:`canvod.utils.pinned`)::

    https://raw.githubusercontent.com/<account>/<repo>/<commit>/<path>/canvod-settings.yaml

A receiver whose ``recipe:`` is a name gets its recipe from the same
repository at the same pin, from ``recipes/<site>/<name>.yaml`` next to
the settings file, as in a local configuration folder. A ``recipe:`` that
is a URL is fetched by the recipe lookup, as with local settings.

:func:`resolve_config_dir` fetches the settings file and those recipes and
puts them into a configuration folder in the cache; everything after it
reads that folder as it reads a local one. The folder also records where
the settings came from (:func:`settings_source`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from canvod.utils.pinned import (
    PinnedFetchError,
    PinnedURLError,
    cache_dir,
    fetch_pinned,
    is_url,
    parse_pinned_url,
)

SETTINGS_FILE = "canvod-settings.yaml"

#: Written into a configuration folder made from a URL; names its source.
SOURCE_FILE = "settings-source.json"


@dataclass(frozen=True)
class SettingsSource:
    """Where the settings of a configuration folder came from.

    Attributes
    ----------
    url : str
        The settings file's URL.
    commit : str | None
        The commit the URL is pinned to, or None for a tag.
    tag : str | None
        The tag the URL is pinned to, or None for a commit.
    sha256 : str
        The sha256 of the settings file's bytes.
    """

    url: str
    commit: str | None
    tag: str | None
    sha256: str


def resolve_config_dir(url: str) -> Path:
    """The configuration folder of the settings file at ``url``.

    Fetches the settings file and the recipes its receivers name (not
    those given as URLs), unless they are in the cache, and returns a
    folder that holds them as a local configuration folder does:
    ``canvod-settings.yaml`` and ``recipes/<site>/<name>.yaml``.

    Parameters
    ----------
    url : str
        The settings file's URL, pinned to a commit or a tag.

    Returns
    -------
    Path
        The configuration folder, in the cache. Don't edit it: change the
        settings in their repository.

    Raises
    ------
    PinnedURLError
        If the URL is not a pinned raw file link, or a recipe name is a
        path.
    PinnedFetchError
        If the settings file or a recipe cannot be fetched, or the settings
        file is not a YAML mapping.
    """
    pinned = parse_pinned_url(url, what="settings file")
    settings_path = fetch_pinned(
        url, kind="settings", what="settings file", check=_settings_check(url)
    )
    settings = yaml.safe_load(settings_path.read_bytes())

    files = {SETTINGS_FILE: settings_path}
    for site, receiver, name in _recipe_names(settings):
        relative = f"recipes/{site}/{name}.yaml"
        recipe_url = pinned.sibling(relative).url
        try:
            files[relative] = fetch_pinned(recipe_url, kind="recipes", what="recipe")
        except PinnedFetchError as exc:
            msg = (
                f"Receiver '{receiver}' of site '{site}' in the settings file {url} "
                f"names the recipe '{name}', which is read from the same repository "
                f"at the same pin: {exc}"
            )
            raise PinnedFetchError(msg) from None

    source = SettingsSource(
        url=url,
        commit=pinned.commit,
        tag=pinned.tag,
        sha256=_sha256(settings_path),
    )
    folder = _config_folder(source, files)
    return folder


def settings_source(config_dir: Path) -> SettingsSource | None:
    """Where the settings of ``config_dir`` came from, if from a URL.

    Parameters
    ----------
    config_dir : Path
        A configuration folder.

    Returns
    -------
    SettingsSource | None
        The source, or None for a local folder.
    """
    path = Path(config_dir) / SOURCE_FILE
    if not path.is_file():
        return None
    return SettingsSource(**json.loads(path.read_text(encoding="utf-8")))


def _settings_check(url: str):
    def check(data: bytes) -> None:
        try:
            settings = yaml.safe_load(data.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            msg = f"Settings file {url} is not a YAML file: {exc}"
            raise PinnedFetchError(msg) from None
        if not isinstance(settings, dict):
            msg = f"Settings file {url} is not a settings file: it holds no keys and values."
            raise PinnedFetchError(msg)

    return check


def _recipe_names(settings: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(site, receiver, recipe name) of each receiver whose recipe is a name.

    Settings that don't have the expected shape are skipped here; loading
    the settings reports them.
    """
    found = []
    sites = settings.get("sites")
    for site, site_settings in (sites if isinstance(sites, dict) else {}).items():
        receivers = (
            site_settings.get("receivers") if isinstance(site_settings, dict) else None
        )
        for receiver, receiver_settings in (
            receivers if isinstance(receivers, dict) else {}
        ).items():
            name = (
                receiver_settings.get("recipe")
                if isinstance(receiver_settings, dict)
                else None
            )
            if not isinstance(name, str) or not name or is_url(name):
                continue
            if (
                any(c in name for c in "/\\")
                or name.startswith(".")
                or "/" in str(site)
            ):
                msg = (
                    f"Receiver '{receiver}' of site '{site}' has the recipe name "
                    f"'{name}': a recipe name is a file name without folders."
                )
                raise PinnedURLError(msg)
            found.append((str(site), str(receiver), name))
    return found


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_folder(source: SettingsSource, files: dict[str, Path]) -> Path:
    """A folder in the cache with ``files`` (relative path -> cached file).

    The folder's name follows from the source and the files' content, so a
    folder that exists holds the same files; parallel runs may build it at
    once, and the first one to finish wins.
    """
    record = json.dumps(asdict(source), indent=2, sort_keys=True)
    listing = {relative: _sha256(path) for relative, path in sorted(files.items())}
    key = hashlib.sha256((record + json.dumps(listing)).encode("utf-8")).hexdigest()
    parent = cache_dir("config")
    folder = parent / key[:32]
    if (folder / SOURCE_FILE).is_file():
        return folder
    building = Path(tempfile.mkdtemp(dir=parent, prefix=".part-"))
    try:
        for relative, path in files.items():
            target = building / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        (building / SOURCE_FILE).write_text(record + "\n", encoding="utf-8")
        try:
            os.rename(building, folder)
        except OSError:
            if not (folder / SOURCE_FILE).is_file():
                raise
    except OSError as exc:
        msg = f"Cannot write the configuration folder {folder}: {exc}"
        raise PinnedFetchError(msg) from exc
    finally:
        shutil.rmtree(building, ignore_errors=True)
    return folder
