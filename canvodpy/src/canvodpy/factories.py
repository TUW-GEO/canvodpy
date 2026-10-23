"""
Component factories for extensible VOD workflow.

Factories enforce ABC compliance and provide Pydantic validation for
community-contributed readers, grids, and calculators.

Examples
--------
Register and create a reader:

    >>> from canvodpy.factories import ReaderFactory
    >>> from canvod.readers import Rnxv3Obs
    >>>
    >>> ReaderFactory.register("rinex3", Rnxv3Obs)
    >>> reader = ReaderFactory.create("rinex3", path="data.rnx")

Create a grid:

    >>> from canvodpy.factories import GridFactory
    >>> grid = GridFactory.create(
    ...     "equal_area",
    ...     angular_resolution=5.0,
    ...     cutoff_theta=75.0,
    ... )

Community extension:

    >>> from canvodpy.factories import VODFactory
    >>> from my_package import MLVODCalculator
    >>>
    >>> VODFactory.register("ml_vod", MLVODCalculator)
    >>> calc = VODFactory.create("ml_vod", model_path="model.pt")
"""

from __future__ import annotations

from abc import ABC
from typing import Any, ClassVar, TypeVar

import structlog

from canvod.utils.tools import deprecated

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=ABC)


class ComponentFactory[T: ABC]:
    """
    Generic factory for creating validated components.

    Enforces ABC compliance and validates kwargs at creation time.

    Type Parameters
    ---------------
    T : type, bound=ABC
        The abstract base class that all components must inherit from.

    Notes
    -----
    This is a generic factory base class. Use specialized subclasses:
    ReaderFactory, GridFactory, VODFactory, AugmentationFactory.
    """

    _registry: ClassVar[dict[str, type[Any]]] = {}
    _abc_class: ClassVar[type[ABC] | None] = None

    @classmethod
    def register(
        cls, name: str, component_class: type[T], *, replace: bool = False
    ) -> None:
        """
        Register a component implementation.

        Parameters
        ----------
        name : str
            Unique identifier for this component (e.g., "rinex3").
        component_class : type[T]
            Component class that inherits from the required ABC.
        replace : bool, default False
            Replace the class already registered under ``name``. Without
            it, a name that is taken is an error.

        Raises
        ------
        TypeError
            If component_class doesn't inherit from the required ABC.
        ValueError
            If ``name`` is already registered and ``replace`` is False.

        Examples
        --------
        >>> ReaderFactory.register("rinex3", Rnxv3Obs)
        """
        if cls._abc_class and not issubclass(component_class, cls._abc_class):
            msg = (
                f"{component_class.__name__} must inherit from "
                f"{cls._abc_class.__name__}"
            )
            raise TypeError(msg)
        if name in cls._registry and not replace:
            msg = (
                f"'{name}' is already registered in {cls.__name__} as "
                f"{cls._registry[name].__name__}. Choose another name, or "
                "pass replace=True to replace it."
            )
            raise ValueError(msg)

        cls._registry[name] = component_class
        log.info(
            "component_registered",
            factory=cls.__name__,
            name=name,
            component=component_class.__name__,
        )

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> T:
        """
        Create a component instance.

        Parameters
        ----------
        name : str
            Registered component name.
        **kwargs : Any
            Component initialization parameters (validated by Pydantic).

        Returns
        -------
        T
            Component instance.

        Raises
        ------
        ValueError
            If component name not registered.
        ValidationError
            If kwargs don't match component requirements (Pydantic).

        Examples
        --------
        >>> reader = ReaderFactory.create("rinex3", path="data.rnx")
        >>> grid = GridFactory.create(
        ...     "equal_area", angular_resolution=5.0
        ... )
        """
        component_class = cls.component_class(name)
        log.debug(
            "component_creating",
            factory=cls.__name__,
            name=name,
            component=component_class.__name__,
        )

        # Pydantic validation happens here
        return component_class(**kwargs)

    @classmethod
    def component_class(cls, name: str) -> type[T]:
        """
        Registered class of a component.

        Raises
        ------
        ValueError
            If component name not registered.
        """
        if name not in cls._registry:
            available = list(cls._registry.keys())
            msg = (
                f"Component '{name}' not registered in {cls.__name__}. "
                f"Available: {available}"
            )
            raise ValueError(msg)
        return cls._registry[name]

    @classmethod
    def list_available(cls) -> list[str]:
        """
        List all registered component names.

        Returns
        -------
        list[str]
            Registered component identifiers.

        Examples
        --------
        >>> ReaderFactory.list_available()
        ['rinex3', 'rinex2', 'custom_reader']
        """
        return list(cls._registry.keys())


class ReaderFactory(ComponentFactory):
    """
    Factory for GNSS data readers.

    All registered readers must inherit from `GNSSDataReader` ABC.

    Supports two creation modes:

    - **By name:** ``ReaderFactory.create("rinex3", fpath=path)``
    - **By file:** ``ReaderFactory.create_from_file(path)`` — detects
      RINEX v2, RINEX v3 and NMEA from the file's content (not SBF).

    Examples
    --------
    >>> from canvodpy import ReaderFactory
    >>> reader = ReaderFactory.create("rinex3", fpath="station.25o")

    >>> reader = ReaderFactory.create_from_file("station.25o")
    """

    _registry: ClassVar[dict[str, type]] = {}

    #: Maps detected format identifiers to registered component names.
    _format_aliases: ClassVar[dict[str, str]] = {
        "rinex_v3": "rinex3",
        "rinex_v3_stripped": "rinex3_stripped",
        "rinex_v2": "rinex2",
        "nmea": "nmea",
    }

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.readers.base import GNSSDataReader

            cls._abc_class = GNSSDataReader

    @classmethod
    def create_from_file(cls, fpath: str | Any, **kwargs: Any) -> Any:
        """Auto-detect the file format and create the appropriate reader.

        Detects NMEA (a ``.nmea`` extension or a first line starting with
        ``$``), and otherwise RINEX v2 or v3 from the version in the first
        header line; a RINEX v3 file with signal-strength observables only
        gets the stripped RINEX v3 reader. SBF files are not detected: create
        their reader by name.

        Parameters
        ----------
        fpath : str or Path
            Path to the GNSS data file.
        **kwargs : Any
            Additional parameters forwarded to the reader constructor.

        Returns
        -------
        GNSSDataReader
            Instantiated reader for the detected format.

        Raises
        ------
        FileNotFoundError
            If *fpath* does not exist.
        ValueError
            If the format cannot be determined or no reader is registered
            for the detected format.
        """
        return cls.create(cls.detect_reader(fpath), fpath=fpath, **kwargs)

    @classmethod
    def detect_reader(cls, fpath: str | Any) -> str:
        """Name of the registered reader for the file at *fpath*.

        Decided as in :meth:`create_from_file`: NMEA by its ``.nmea``
        extension or its sentences, RINEX by the version in the first
        header line.

        Raises
        ------
        FileNotFoundError
            If *fpath* does not exist.
        ValueError
            If the format cannot be determined or no reader is registered
            for the detected format.
        """
        from pathlib import Path

        fpath = Path(fpath)
        if not fpath.exists():
            msg = f"File not found: {fpath}"
            raise FileNotFoundError(msg)

        format_id = cls._detect_format(fpath)
        name = cls._format_aliases.get(format_id, format_id)

        if name not in cls._registry:
            msg = (
                f"No reader registered for detected format {format_id!r} "
                f"(mapped to {name!r}). Available: {list(cls._registry.keys())}"
            )
            raise ValueError(msg)

        log.debug(
            "auto_detected_format",
            file=str(fpath.name),
            format=format_id,
            reader=name,
        )
        return name

    @staticmethod
    def _detect_format(fpath: Any) -> str:
        """Detect the file format from the extension and the file header.

        Parameters
        ----------
        fpath : Path
            Path to the file.

        Returns
        -------
        str
            Format identifier: ``"nmea"``, ``"rinex_v2"``, ``"rinex_v3"`` or
            ``"rinex_v3_stripped"``.
        """
        from pathlib import Path

        fpath = Path(fpath)

        # Detect NMEA by extension before attempting RINEX header parse
        if fpath.suffix.lower() == ".nmea":
            return "nmea"

        with fpath.open() as f:
            first_line = f.readline()
            header_lines: list[str] = []
            for line in f:
                header_lines.append(line)
                if "END OF HEADER" in line:
                    break

        # NMEA sentences start with '$'
        if first_line.startswith("$"):
            return "nmea"

        try:
            version_str = first_line[:9].strip()
            version = float(version_str)
        except (ValueError, IndexError) as e:
            msg = f"Cannot determine file format from first line: {e}"
            raise ValueError(msg) from e

        if 3.0 <= version < 4.0:
            if ReaderFactory._is_stripped_v3(header_lines):
                return "rinex_v3_stripped"
            return "rinex_v3"
        if 2.0 <= version < 3.0:
            return "rinex_v2"
        msg = f"Unsupported RINEX version: {version}"
        raise ValueError(msg)

    @staticmethod
    def _is_stripped_v3(header_lines: list[str]) -> bool:
        """Return True if every ``SYS / # / OBS TYPES`` code starts with ``S``.

        A stripped RINEX v3 file contains signal-strength observables only.
        Header lines wrap at 13 codes, but every wrapped continuation also
        starts with a system letter or whitespace continuation, so we scan all
        ``SYS / # / OBS TYPES`` records together.
        """
        codes: list[str] = []
        for line in header_lines:
            if "SYS / # / OBS TYPES" not in line:
                continue
            payload = line[:60]
            tokens = payload.split()
            for tok in tokens:
                if len(tok) == 3 and tok[0] in "CLDS":
                    codes.append(tok)
        if not codes:
            return False
        return all(c.startswith("S") for c in codes)


class GridFactory(ComponentFactory):
    """
    Factory for grid builders.

    All registered builders must inherit from `BaseGridBuilder` ABC.

    Examples
    --------
    >>> from canvod.grids import EqualAreaBuilder
    >>> GridFactory.register("equal_area", EqualAreaBuilder)
    >>> grid = GridFactory.create(
    ...     "equal_area",
    ...     angular_resolution=5.0,
    ...     cutoff_theta=75.0,
    ... )
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.grids.core.grid_builder import BaseGridBuilder

            cls._abc_class = BaseGridBuilder


class VODFactory(ComponentFactory):
    """
    Factory for VOD calculators.

    All registered calculators must inherit from `VODCalculator` ABC.

    Examples
    --------
    >>> from canvod.vod import TauOmegaZerothOrder
    >>> VODFactory.register("tau_omega", TauOmegaZerothOrder)
    >>> calc = VODFactory.create(
    ...     "tau_omega",
    ...     canopy_ds=canopy,
    ...     sky_ds=sky,
    ... )
    >>> vod = calc.calculate_vod()
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.vod.calculator import VODCalculator

            cls._abc_class = VODCalculator


_AUGMENTATION_LEFT_OVER = (
    "`AugmentationFactory` is left over from development and will be removed "
    "with the next major version. Write a `canvod.ops.Op` and run it in a "
    "`canvod.ops.Pipeline` instead."
)


@deprecated(_AUGMENTATION_LEFT_OVER)
class AugmentationFactory(ComponentFactory):
    """
    Factory for data augmentation steps.

    All registered steps must inherit from `AugmentationStep` ABC.

    Examples
    --------
    >>> from canvod.auxiliary.augmentation import ClockCorrectionAugmentation
    >>> AugmentationFactory.register("clock", ClockCorrectionAugmentation)
    >>> step = AugmentationFactory.create("clock")
    """

    _registry: ClassVar[dict[str, type]] = {}

    @classmethod
    def _set_abc_class(cls) -> None:
        """Lazy import to avoid circular dependencies."""
        if cls._abc_class is None:
            from canvod.auxiliary.augmentation import AugmentationStep

            cls._abc_class = AugmentationStep

    @classmethod
    @deprecated(_AUGMENTATION_LEFT_OVER)
    def register(
        cls, name: str, component_class: type, *, replace: bool = False
    ) -> None:
        """Deprecated: augmentation steps are not used by ``canvodpy run``."""
        super().register(name, component_class, replace=replace)

    @classmethod
    @deprecated(_AUGMENTATION_LEFT_OVER)
    def create(cls, name: str, **kwargs: Any) -> Any:
        """Deprecated: augmentation steps are not used by ``canvodpy run``."""
        return super().create(name, **kwargs)

    @classmethod
    @deprecated(_AUGMENTATION_LEFT_OVER)
    def list_available(cls) -> list[str]:
        """Deprecated: augmentation steps are not used by ``canvodpy run``."""
        return super().list_available()


def register_plugins() -> None:
    """Register the reader and VOD calculator plugins of installed packages.

    Plugins are declared as entry points (groups ``canvodpy.readers`` and
    ``canvodpy.vod_calculators``, see :mod:`canvod.utils.plugins`) and
    registered under their entry point name, after the built-in components.

    Raises
    ------
    canvod.utils.plugins.PluginError
        If a plugin cannot be imported, does not inherit the required base
        class, takes the name of a built-in component, or (readers) sets no
        valid ``file_type``. The message names the plugin's package.
    """
    from canvod.preflight.convention import known_file_types
    from canvod.utils.plugins import (
        READER_GROUP,
        VOD_CALCULATOR_GROUP,
        PluginError,
        load_plugins,
        plugin_package,
    )

    factories: tuple[tuple[str, type[ComponentFactory]], ...] = (
        (READER_GROUP, ReaderFactory),
        (VOD_CALCULATOR_GROUP, VODFactory),
    )
    for group, factory in factories:
        taken = {*factory.list_available(), "auto"}
        for name, plugin in load_plugins(group).items():
            package = plugin_package(group, name)
            if name in taken:
                raise PluginError(
                    f"The {group} plugin '{name}' of the package {package} "
                    "takes the name of a built-in component. Rename the entry "
                    f"point in {package}."
                )
            try:
                factory.register(name, plugin)
            except TypeError as exc:
                raise PluginError(
                    f"The {group} plugin '{name}' of the package {package} "
                    f"cannot be used: {exc}."
                ) from exc
    known_file_types()
