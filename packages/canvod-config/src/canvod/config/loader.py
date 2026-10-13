"""Configuration loader for canvodpy."""

import functools
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import CanvodConfig, ProcessingConfig, SidsConfig, SitesConfig


class ConfigValidationError(ValueError):
    """Raised when configuration YAML fails Pydantic validation.

    Attributes
    ----------
    validation_error : ValidationError
        The underlying Pydantic validation error.
    config_dir : Path
        The config directory that was loaded.
    """

    def __init__(self, error: ValidationError, config_dir: Path) -> None:
        self.validation_error = error
        self.config_dir = config_dir
        super().__init__(str(error))


def format_validation_error(error: ConfigValidationError) -> str:
    """Format a ConfigValidationError as human-readable, actionable text.

    Leads with the dotted field path (e.g. ``processing.metadata.author``)
    so a user can jump straight to the offending key in their YAML, strips
    Pydantic's ``"Value error, "`` prefix (added when a custom validator
    raises a plain ``ValueError``) and its ``https://errors.pydantic.dev/...``
    footer — both are developer-facing noise for a config-file typo, not
    something a scientist editing YAML needs to see.

    Parameters
    ----------
    error : ConfigValidationError
        The error raised by ``ConfigLoader.load()``.

    Returns
    -------
    str
        Multi-line, human-readable error report.
    """
    settings_file = error.config_dir / "canvod-settings.yaml"
    lines = [f"Configuration error in {settings_file}:", ""]
    for err in error.validation_error.errors():
        loc = ".".join(str(part) for part in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"  {loc}")
        lines.append(f"    {msg}")
        lines.append("")
    return "\n".join(lines).rstrip()


def find_monorepo_root() -> Path:
    """Find the monorepo root by looking for a .git entry.

    A repo root's ``.git`` is a directory for a normal clone, but a file
    (containing a ``gitdir:`` pointer) for a git worktree or submodule — both
    are valid roots, so any ``.git`` entry (file or directory) counts.

    Returns
    -------
    Path
        Monorepo root directory.

    Raises
    ------
    RuntimeError
        If the monorepo root cannot be found.
    """
    current = Path.cwd().resolve()

    # Walk up directory tree looking for a .git entry (directory or file).
    for parent in [current, *list(current.parents)]:
        git_path = parent / ".git"
        if git_path.exists():
            return parent

    raise RuntimeError("Cannot find monorepo root (no .git entry found)")


def get_template_dir() -> Path:
    """Return the directory containing bundled config templates.

    Fixed, package-relative path — ``templates/`` ships inside the
    ``canvod-config`` wheel as real package data (verified: ``uv_build``
    includes non-Python files under the module's source tree automatically,
    same as the pre-existing ``defaults/`` directory). No monorepo-root
    search needed here, unlike config *output* location below — the
    templates always live at a fixed path relative to this installed module,
    regardless of install method (editable checkout, wheel, ``uv tool
    install``) or invocation directory.

    Returns
    -------
    Path
        Directory containing ``canvod-settings.yaml.example``.
    """
    return Path(__file__).parent / "templates"


def get_default_config_dir() -> Path:
    """Resolve the configuration directory.

    This is the only lookup of the configuration directory: the settings
    file (``canvod-settings.yaml``) and the naming recipes (``recipes/``)
    are both read from the directory it returns.

    Priority:
    0. ``CANVOD_CONFIG_DIR``, which the ``--config-dir`` option of every
       ``canvodpy`` command sets.
    1. Dev-mode convenience: if running from within a canvodpy monorepo
       checkout that already has a ``config/`` directory, use
       ``{monorepo_root}/config`` — preserves the existing contributor
       workflow unchanged.
    2. Otherwise, XDG: ``$XDG_CONFIG_HOME/canvodpy`` or
       ``~/.config/canvodpy`` — the real default for a standalone install
       (``uv tool install``/``pipx``/wheel), where no monorepo checkout
       exists at all.

    This is the single shared implementation of what used to be three
    separate "find monorepo root, else cwd()/config" copies (here, in
    ``canvodpy/cli/config.py``'s module-level default, and in that same
    file's ``init`` command): none of which defaulted to a user-level
    location, so a globally-installed CLI invoked from an arbitrary
    directory always ended up looking for ``./config`` right there.

    Returns
    -------
    Path
        Default configuration directory.
    """
    env_dir = os.environ.get("CANVOD_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    try:
        monorepo_root = find_monorepo_root()
        monorepo_config = monorepo_root / "config"
        if monorepo_config.exists():
            return monorepo_config
    except RuntimeError:
        pass

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "canvodpy"


class ConfigLoader:
    """
    Load and merge configuration from YAML files.

    Parameters
    ----------
    config_dir : Path | None, optional
        Directory containing config files. If None, uses monorepo_root/config.
    config_file : Path | None, optional
        Optional overlay YAML file applied on top of the main config.
        Keys in the overlay take precedence over the main file.
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        config_file: Path | None = None,
    ) -> None:
        """Initialize the loader with an optional config directory.

        Parameters
        ----------
        config_dir : Path | None, optional
            Directory containing config files. If None, uses the monorepo
            root config directory or a local fallback.
        config_file : Path | None, optional
            Optional overlay YAML file applied on top of the main config.
        """
        if config_dir is None:
            config_dir = get_default_config_dir()

        self.config_dir = Path(config_dir)
        self.defaults_dir = Path(__file__).parent / "defaults"
        self.config_file: Path | None = None
        if config_file is not None:
            p = Path(config_file)
            if not p.exists():
                msg = f"Overlay config file not found: {p}"
                raise FileNotFoundError(msg)
            self.config_file = p

    def load(self) -> CanvodConfig:
        """
        Load complete configuration.

        Loads ``canvod-settings.yaml`` from the config directory.

        Returns
        -------
        CanvodConfig
            Validated configuration object.

        Raises
        ------
        ConfigValidationError
            If configuration is invalid (wraps Pydantic ValidationError).
        FileNotFoundError
            If ``canvod-settings.yaml`` does not exist in the config directory.
        """
        settings_yaml = self.config_dir / "canvod-settings.yaml"
        if not settings_yaml.exists():
            raise FileNotFoundError(
                f"Settings file not found: {settings_yaml}\n"
                "Run 'canvodpy config init' to create it from the template."
            )
        return self._load_single_file(settings_yaml)

    def _load_single_file(self, path: Path) -> CanvodConfig:
        """Load from a unified settings file (canvod-settings.yaml).

        Expected top-level keys: ``processing:``, ``sites:``, ``sids:``.
        ``sites:`` values are site names directly (no nested ``sites:`` wrapper).
        """
        data = self._load_yaml(path)

        # Processing: merge user section with package defaults.
        proc_defaults = self._load_yaml(self.defaults_dir / "processing.yaml")
        proc_data = self._deep_merge(proc_defaults, data.get("processing", {}))

        # Apply overlay file if set.
        if self.config_file is not None:
            overlay = self._load_yaml(self.config_file)
            overlay_proc = overlay.get("processing", {})
            # Normalize deprecated 'processing:' key in overlay before merging.
            if "processing" in overlay_proc:
                nested = overlay_proc.pop("processing")
                overlay_proc["params"] = self._deep_merge(
                    overlay_proc.get("params", {}), nested
                )
            proc_data = self._deep_merge(proc_data, overlay_proc)
            sids_overlay = overlay.get("sids", {})
            sites_raw_overlay = overlay.get("sites", {})
        else:
            sids_overlay: dict = {}
            sites_raw_overlay: dict = {}

        # Sids: merge user section with package defaults, then overlay.
        sids_defaults = self._load_yaml(self.defaults_dir / "sids.yaml")
        sids_data = self._deep_merge(sids_defaults, data.get("sids", {}))
        if sids_overlay:
            sids_data = self._deep_merge(sids_data, sids_overlay)

        # Sites: top-level keys in the 'sites:' section are site names.
        sites_raw = data.get("sites", {})
        if sites_raw_overlay:
            sites_raw = self._deep_merge(sites_raw, sites_raw_overlay)

        try:
            return CanvodConfig(
                processing=ProcessingConfig(**proc_data),
                sites=SitesConfig(sites=sites_raw),
                sids=SidsConfig(**sids_data),
            )
        except ValidationError as e:
            raise ConfigValidationError(e, self.config_dir) from e

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """Load YAML file.

        Parameters
        ----------
        path : Path
            Path to YAML file.

        Returns
        -------
        dict[str, Any]
            YAML content (empty dict if file empty).
        """
        with open(path) as f:
            return yaml.safe_load(f) or {}

    def _deep_merge(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """Deep merge override dictionary into base dictionary.

        Parameters
        ----------
        base : dict[str, Any]
            Base dictionary.
        override : dict[str, Any]
            Override dictionary.

        Returns
        -------
        dict[str, Any]
            Merged dictionary.
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


@functools.lru_cache(maxsize=8)
def _load_config_cached(
    config_dir: Path | None,
    config_file: Path | None,
) -> CanvodConfig:
    loader = ConfigLoader(config_dir, config_file=config_file)
    return loader.load()


def load_config(
    config_dir: Path | None = None,
    config_file: Path | None = None,
) -> CanvodConfig:
    """Load configuration from YAML files.

    This is the main entry point for loading configuration.

    Parameters
    ----------
    config_dir : Path | None, optional
        Directory containing config files. If None, automatically finds
        monorepo root and uses {monorepo_root}/config.
    config_file : Path | None, optional
        Optional overlay YAML file applied on top of the main config.
        Can also be set via the ``CANVOD_CONFIG_FILE`` environment variable.

    Returns
    -------
    CanvodConfig
        Validated configuration object.

    Raises
    ------
    ConfigValidationError
        If configuration YAML is invalid.
    FileNotFoundError
        If ``config_file`` is specified but does not exist.

    Notes
    -----
    ``CANVOD_CONFIG_DIR``/``CANVOD_CONFIG_FILE`` are resolved here, *before*
    the cached call, not inside it. The actual caching happens in
    ``_load_config_cached``, keyed on the fully-resolved paths. Resolving
    the env vars inside the cached function itself (as this used to do)
    made the cache key blind to them: whichever call happened first in a
    process -- e.g. ``canvodpy.logging.logging_config``'s module-level
    ``LOGGER = configure_logging()``, which called ``load_config()`` bare at
    import time until 2026-10, before a CLI's ``--config``/``CANVOD_CONFIG_FILE`` is ever
    set -- would cache the config under the no-arg key, and every later
    bare ``load_config()`` call in that process (e.g. store-path/chunk-
    strategy resolution deep in ``canvod-store``) would silently get that
    stale, pre-overlay config back, no matter what the env var said by
    then. See ``canvodpy/tests/test_cli_store.py``'s ``_clear_config_cache``
    fixture for a hand-rolled workaround of the same symptom that predates
    this fix.

    Examples
    --------
    >>> from canvod.config import load_config
    >>> config = load_config()
    >>> print(config.nasa_earthdata_acc_mail)
    >>> print(config.processing.aux_data.agency)
    """
    if config_dir is None:
        config_dir = get_default_config_dir()
    if config_file is None:
        env_file = os.environ.get("CANVOD_CONFIG_FILE")
        if env_file:
            config_file = Path(env_file)
    return _load_config_cached(config_dir, config_file)


# Backwards-compatible cache introspection/control on the public name --
# some tests/callers reach for `load_config.cache_clear()`/`.cache_info()`
# directly (the function used to be the lru_cache-wrapped one itself). ty
# can't model attributes bolted onto a plain function.
load_config.cache_clear = _load_config_cached.cache_clear  # ty: ignore[unresolved-attribute]
load_config.cache_info = _load_config_cached.cache_info  # ty: ignore[unresolved-attribute]
