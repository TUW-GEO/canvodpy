"""The settings file read from a URL.

``canvodpy -c URL`` (or ``CANVOD_CONFIG_DIR=URL``) reads the settings file
from a GitHub repository, at a commit, a tag or a branch (the URL rules of
:mod:`canvod.utils.remote_file`)::

    https://raw.githubusercontent.com/<account>/<repo>/<commit, tag or branch>/<path>/canvod-settings.yaml

A receiver whose ``recipe:`` is a name gets its recipe from the same
repository at the same link, from ``recipes/<site>/<name>.yaml`` next to
the settings file, as in a local configuration folder. A ``recipe:`` that
is a URL is fetched by the recipe lookup, as with local settings.

:func:`resolve_config_dir` fetches the settings file and those recipes,
once per run, and puts them into a configuration folder of the run;
everything after it reads that folder as it reads a local one. The URL is
not recorded: stores and the run history keep the settings, not where
they came from.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from canvod.config.models.sites import RECIPE_SETTINGS
from canvod.utils.remote_file import (
    RemoteFetchError,
    RemoteURLError,
    fetch_remote,
    is_url,
    parse_remote_url,
    run_folder,
)

SETTINGS_FILE = "canvod-settings.yaml"

# The configuration folder of each run folder and settings URL. The entries
# of a run folder that is gone (removed by new_run) are dropped.
_FOLDERS: dict[tuple[Path, str], Path] = {}
_LOCK = threading.Lock()


def resolve_config_dir(url: str) -> Path:
    """The configuration folder of the settings file at ``url``.

    Fetches the settings file and the recipes its receivers name (not
    those given as URLs) and returns a folder that holds them as a local
    configuration folder does: ``canvod-settings.yaml`` and
    ``recipes/<site>/<name>.yaml``. A run fetches them once
    (:func:`canvod.utils.remote_file.new_run` starts a new run); the folder
    is removed with its run folder.

    Parameters
    ----------
    url : str
        The settings file's URL.

    Returns
    -------
    Path
        The configuration folder. Don't edit it: change the settings in
        their repository.

    Raises
    ------
    RemoteURLError
        If the URL is not a raw file link, or a recipe name is a path.
    RemoteFetchError
        If the settings file or a recipe cannot be fetched, or the settings
        file is not a YAML mapping.
    """
    key = (run_folder(), url)
    with _LOCK:
        _drop_removed()
        folder = _FOLDERS.get(key)
    if folder is not None and folder.is_dir():
        return folder
    remote = parse_remote_url(url, what="settings file")
    settings_path = fetch_remote(url, what="settings file", check=_settings_check(url))
    settings = yaml.safe_load(settings_path.read_bytes())

    files = {SETTINGS_FILE: settings_path}
    for site, receiver, name in _recipe_names(settings):
        relative = f"recipes/{site}/{name}.yaml"
        recipe_url = remote.sibling(relative).url
        try:
            files[relative] = fetch_remote(recipe_url, what="recipe")
        except RemoteFetchError as exc:
            msg = (
                f"Receiver '{receiver}' of site '{site}' in the settings file {url} "
                f"names the recipe '{name}', which is read from the same repository "
                f"at the same link: {exc}"
            )
            raise RemoteFetchError(msg) from None

    folder = _config_folder(files)
    with _LOCK:
        _FOLDERS[key] = folder
    return folder


def settings_url(config_dir: Path) -> str | None:
    """The URL this process read the settings of ``config_dir`` from.

    For ``canvodpy doctor``, which shows it in the terminal; it is never
    recorded.

    Parameters
    ----------
    config_dir : Path
        A configuration folder.

    Returns
    -------
    str | None
        The settings file's URL, or None for a local folder.
    """
    config_dir = Path(config_dir).resolve()
    with _LOCK:
        _drop_removed()
        for (_, url), folder in _FOLDERS.items():
            if folder.resolve() == config_dir:
                return url
    return None


def _drop_removed() -> None:
    """Drop the entries whose run folder is gone; call with ``_LOCK`` held."""
    for key in [key for key in _FOLDERS if not key[0].is_dir()]:
        del _FOLDERS[key]


def _settings_check(url: str):
    def check(data: bytes) -> None:
        try:
            settings = yaml.safe_load(data.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            msg = f"Settings file {url} is not a YAML file: {exc}"
            raise RemoteFetchError(msg) from None
        if not isinstance(settings, dict):
            msg = f"Settings file {url} is not a settings file: it holds no keys and values."
            raise RemoteFetchError(msg)

    return check


def _recipe_names(settings: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(site, receiver, recipe name) of each recipe setting that is a name.

    A receiver names up to two recipes, ``recipe`` and ``nav_recipe``.

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
            for key in RECIPE_SETTINGS:
                name = (
                    receiver_settings.get(key)
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
                        f"Receiver '{receiver}' of site '{site}' has the {key} "
                        f"name '{name}': a recipe name is a file name without "
                        "folders."
                    )
                    raise RemoteURLError(msg)
                found.append((str(site), str(receiver), name))
    return found


def _config_folder(files: dict[str, Path]) -> Path:
    """A new folder of the run with ``files`` (relative path -> fetched file)."""
    parent = run_folder() / "config"
    parent.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(dir=parent))
    try:
        for relative, path in files.items():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    except OSError as exc:
        msg = f"Cannot write the configuration folder {folder}: {exc}"
        raise RemoteFetchError(msg) from exc
    return folder
