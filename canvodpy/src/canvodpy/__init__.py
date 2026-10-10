"""canvodpy: GNSS Vegetation Optical Depth Analysis.

A modern Python package for processing GNSS data and calculating
vegetation optical depth (VOD) using the tau-omega model.

Quick Start
-----------
**Site processing, from the terminal** (production runs, resumable)::

    canvodpy run

**Site processing, from Python** (same logic as ``canvodpy run``)
    >>> from canvodpy import Site
    >>> site = Site("ExampleSite")
    >>> with site.pipeline() as pipeline:
    ...     data = pipeline.process_date("2025001")
    >>> vod = site.vod.compute_day_all(data)  # every configured analysis

The single-step functions of ``canvodpy.functional`` (``read_rinex`` and
the others) are deprecated: they are no longer maintained and give different
results than ``canvodpy run``.

Community Extensions
--------------------
Extend canvodpy with custom components using factories:

    >>> from canvodpy import VODFactory
    >>> from my_package import CustomCalculator
    >>> VODFactory.register("custom", CustomCalculator)
    >>> calc = VODFactory.create("custom", **params)

Package Structure
-----------------
- canvod.readers - RINEX file parsing
- canvod.auxiliary - Auxiliary data (ephemeris, clocks)
- canvod.grids - Hemisphere grid structures
- canvod.vod - VOD calculation algorithms
- canvod.viz - 2D/3D visualization
- canvod.store - Icechunk data storage

Configuration
-------------
Site configurations are stored in the ``sites:`` section of
``config/canvod-settings.yaml``.
Default variables and settings are in `globals.py`.

Examples
--------
Process a week, computing VOD for every configured analysis per day:
    >>> from canvodpy import Site
    >>> site = Site("ExampleSite")
    >>> with site.pipeline() as pipeline:
    ...     for date, datasets in pipeline.process_range("2025001", "2025007"):
    ...         site.vod.compute_day_all(datasets)

"""

from canvodpy.api import (
    Pipeline,
    Site,
    calculate_vod,
    preview_processing,
    process_date,
)

# Factories (for community extensions)
from canvodpy.factories import (
    AugmentationFactory,
    GridFactory,
    ReaderFactory,
    VODFactory,
    register_plugins,
)

# Fluent workflow API (deferred execution)
from canvodpy.fluent import FluentWorkflow

# Functional API (deprecated, see canvodpy.functional)
from canvodpy.functional import (
    assign_grid_cells,
    assign_grid_cells_to_file,
    augment_with_ephemeris,
    calculate_vod_to_file,
    create_grid,
    create_grid_to_file,
    read_rinex,
    read_rinex_to_file,
)

# Logging (for all users)
from canvodpy.logging import get_logger, setup_logging

# VOD computation helper
from canvodpy.vod_computer import VodComputer

# New workflow API
from canvodpy.workflow import VODWorkflow


def workflow(site: str, **kwargs) -> FluentWorkflow:
    """Create a fluent workflow with deferred execution.

    Parameters
    ----------
    site : str
        Site name (e.g. ``"ExampleSite"``).
    **kwargs
        Forwarded to :class:`FluentWorkflow`.

    Returns
    -------
    FluentWorkflow

    Examples
    --------
    >>> import canvodpy
    >>> result = (canvodpy.workflow("ExampleSite")
    ...     .read("2025001")
    ...     .preprocess()
    ...     .grid()
    ...     .vod("canopy_01", "reference_01")
    ...     .result())
    """
    return FluentWorkflow(site, **kwargs)


# ============================================================================
# Level 3 API: Re-export subpackages for advanced users
# ============================================================================


# Lazy import subpackages on access to avoid circular dependencies
def __getattr__(name: str):
    """Lazy import subpackages when accessed."""
    _subpackages = {
        "auxiliary": "canvod.auxiliary",
        "grids": "canvod.grids",
        "readers": "canvod.readers",
        "store": "canvod.store",
        "viz": "canvod.viz",
        "vod": "canvod.vod",
    }

    if name in _subpackages:
        import importlib
        import sys

        module = importlib.import_module(_subpackages[name])
        # Cache the imported module (can't use globals() as it's shadowed by canvodpy.globals)
        setattr(sys.modules[__name__], name, module)
        return module

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Type-checker stubs so that static analysis tools (CodeQL, mypy, pyright) can
# resolve the subpackage names that are lazily loaded via __getattr__ at runtime.
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import canvod.auxiliary as auxiliary
    import canvod.grids as grids
    import canvod.readers as readers
    import canvod.store as store
    import canvod.viz as viz
    import canvod.vod as vod


# ============================================================================
# Version
# ============================================================================

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("canvodpy")
except Exception:  # pragma: no cover — not installed as a package (rare)
    __version__ = "0.0.0+unknown"

# ============================================================================
# Public API
# ============================================================================

__all__ = [  # noqa: RUF022
    # Version
    "__version__",
    # High-level API (most users)
    "Site",
    "Pipeline",
    "process_date",
    "calculate_vod",
    "preview_processing",
    # New workflow API
    "VODWorkflow",
    # Fluent workflow API
    "FluentWorkflow",
    "workflow",
    # Functional API (notebooks & Airflow)
    "read_rinex",
    "read_rinex_to_file",
    "create_grid",
    "create_grid_to_file",
    "assign_grid_cells",
    "assign_grid_cells_to_file",
    "calculate_vod_to_file",
    # Logging
    "setup_logging",
    "get_logger",
    # Factories (community extensions)
    "ReaderFactory",
    "GridFactory",
    "VODFactory",
    "AugmentationFactory",
    # Subpackages (advanced users — lazy-loaded via __getattr__)
    "readers",
    "auxiliary",
    "grids",
    "vod",
    "viz",
    "store",
]


# ============================================================================
# Auto-register built-in components
# ============================================================================


def _register_builtin_components() -> None:
    """
    Register built-in component implementations.

    Called automatically on package import. Registers the readers
    ``rinex3``, ``rinex3_stripped``, ``rinex2``, ``sbf`` and ``nmea``, the
    grid builders ``equal_area``, ``equal_angle``, ``equirectangular``,
    ``htm``, ``geodesic``, ``healpix`` and ``fibonacci`` (the values of
    :class:`canvod.grids.GridType`, with the builders of
    :data:`canvod.grids.GRID_BUILDERS`, which ``create_hemigrid`` also uses)
    and the VOD calculator ``tau_omega``. All
    of them come from declared dependencies of canvodpy, so a failed
    import raises instead of leaving a component unregistered.
    """
    log = structlog.get_logger(__name__)

    # Set ABC classes for validation
    ReaderFactory._set_abc_class()
    GridFactory._set_abc_class()
    VODFactory._set_abc_class()
    AugmentationFactory._set_abc_class()

    from canvod.grids import GRID_BUILDERS
    from canvod.readers import Rnxv3Obs
    from canvod.readers.nmea import NmeaObs
    from canvod.readers.rinex import Rnxv2Obs, Rnxv3StrippedObs
    from canvod.readers.sbf import SbfReader
    from canvod.vod.calculator import TauOmegaZerothOrder

    ReaderFactory.register("rinex3", Rnxv3Obs)
    ReaderFactory.register("rinex3_stripped", Rnxv3StrippedObs)
    ReaderFactory.register("sbf", SbfReader)
    ReaderFactory.register("rinex2", Rnxv2Obs)
    ReaderFactory.register("nmea", NmeaObs)
    # The same builders create_hemigrid uses, under the values of GridType
    for grid_type, builder in GRID_BUILDERS.items():
        GridFactory.register(grid_type.value, builder)
    VODFactory.register("tau_omega", TauOmegaZerothOrder)

    log.info("builtin_components_registered")


# Auto-register on import; plugins after the built-ins, so a name clash fails
_register_builtin_components()
register_plugins()
