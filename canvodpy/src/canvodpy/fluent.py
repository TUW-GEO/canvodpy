"""Fluent workflow API with deferred execution.

.. deprecated::
    Use ``Site(site).pipeline()`` to process data and ``Site(site).vod``
    to compute VOD. Removed with the next major version.
    ``FluentWorkflow`` emits a ``FutureWarning`` on instantiation.

Provides a chainable, lazy pipeline where steps are recorded and
executed only when a terminal method is called.

Examples
--------
Process RINEX data and compute VOD:

    >>> import canvodpy
    >>> result = (canvodpy.workflow("ExampleSite")
    ...     .read("2025001")
    ...     .preprocess(agency="COD")
    ...     .grid("equal_area", angular_resolution=5.0)
    ...     .vod("canopy_01", "reference_01")
    ...     .result())

Preview the execution plan without running it:

    >>> plan = (canvodpy.workflow("ExampleSite")
    ...     .read("2025001")
    ...     .preprocess()
    ...     .grid()
    ...     .vod("canopy_01", "reference_01")
    ...     .explain())

"""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Any

import structlog

from canvod.utils.tools import deprecated
from canvodpy.api import Site
from canvodpy.factories import GridFactory, ReaderFactory, VODFactory

#: File format that discovery selects for each reader (see
#: :func:`canvodpy.orchestrator.discovery.discover_files`).
_READER_FILE_FORMATS = {
    "rinex3": "rinex3",
    "rinex3_stripped": "rinex3",
    "rinex2": "rinex",
    "rinex_v2": "rinex",
    "sbf": "sbf",
}

if TYPE_CHECKING:
    import xarray as xr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _concat_epoch_datasets(datasets: list) -> Any:
    """Concatenate xarray Datasets along 'epoch' without xr.concat overhead.

    Direct numpy concatenation bypasses xarray's alignment checks and
    intermediate copies. Safe when all datasets share the same 'sid' axis,
    which is guaranteed after pad_to_global_sid=True (the default).
    """
    import numpy as np
    import xarray as xr

    if len(datasets) == 1:
        return datasets[0]

    first = datasets[0]
    merged_vars: dict = {}
    for var in first.data_vars:
        epoch_ax = list(first[var].dims).index("epoch")
        merged_vars[var] = (
            first[var].dims,
            np.concatenate([ds[var].values for ds in datasets], axis=epoch_ax),
        )

    coords: dict = {}
    for k, coord in first.coords.items():
        if "epoch" in coord.dims:
            ax = list(coord.dims).index("epoch")
            coords[k] = (
                coord.dims,
                np.concatenate([ds.coords[k].values for ds in datasets], axis=ax),
            )
        else:
            coords[k] = coord

    return xr.Dataset(merged_vars, coords=coords, attrs=first.attrs)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def step(method):
    """Record a pipeline step for deferred execution.

    The decorated method is not called immediately. Instead, a reference
    to the method and its arguments is appended to ``self._plan``.
    The method returns ``self`` so calls can be chained.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        self._plan.append((method, args, kwargs))
        return self

    return wrapper


def terminal(method):
    """Execute all recorded steps, then run the terminal method.

    Iterates over ``self._plan``, calling each recorded step in order,
    then invokes the decorated method and returns its result.  The plan
    is cleared after execution so the workflow can be reused.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        for fn, a, kw in self._plan:
            fn(self, *a, **kw)
        self._plan.clear()
        return method(self, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# FluentWorkflow
# ---------------------------------------------------------------------------


@deprecated(
    "FluentWorkflow is left over from development and will be removed with the next major version. "
    "Use canvodpy.Site(<site>).pipeline() to process data and "
    "canvodpy.Site(<site>).vod to compute VOD instead."
)
class FluentWorkflow:
    """Chainable, deferred-execution workflow for VOD analysis.

    Parameters
    ----------
    site : str or Site
        Site name or :class:`~canvodpy.api.Site` object.
    reader : str
        Registered reader name (default ``"rinex3"``).
    grid_type : str
        Registered grid type (default ``"equal_area"``).
    vod_calculator : str
        Registered VOD calculator (default ``"tau_omega"``).
    keep_vars : list[str], optional
        RINEX variables to retain.  Defaults to :data:`KEEP_RNX_VARS`.
    """

    def __init__(
        self,
        site: str | Site,
        reader: str = "rinex3",
        grid_type: str = "equal_area",
        vod_calculator: str = "tau_omega",
        keep_vars: list[str] | None = None,
    ) -> None:
        self._plan: list[tuple] = []

        # State populated by steps
        self._datasets: dict[str, xr.Dataset] = {}
        self._vod_result: xr.Dataset | None = None
        self._vod_pair: tuple[str, str] | None = None
        self._grid: Any = None
        self._last_date: str | None = None

        # Configuration
        self._site = Site(site) if isinstance(site, str) else site
        self._reader_name = reader
        self._grid_type = grid_type
        self._vod_calculator_name = vod_calculator
        if keep_vars is None:
            from canvod.config import load_config

            keep_vars = load_config().processing.params.keep_gnss_observables
        self._keep_vars = keep_vars

        self.log = structlog.get_logger(__name__).bind(site=self._site.name)

    # ------------------------------------------------------------------
    # Steps (deferred)
    # ------------------------------------------------------------------

    @step
    def read(self, date: str, receivers: list[str] | None = None) -> FluentWorkflow:
        """Load the observations of *date*.

        Files are found as ``canvodpy run`` finds them (see
        :mod:`canvodpy.orchestrator.discovery`): the receiver's naming recipe
        if it has one, otherwise canonical canVOD names only, anywhere below
        the receiver's directory.

        Parameters
        ----------
        date : str
            Date in ``YYYYDOY`` format (e.g. ``"2025001"``).
        receivers : list[str], optional
            Receiver names to load.  If ``None``, all active receivers
            for the site are loaded.

        Raises
        ------
        ValueError
            If files cannot be selected for the workflow's reader.
        """
        self._last_date = date
        receiver_list = receivers or list(self._site.active_receivers.keys())
        log = self.log.bind(date=date)

        from canvod.config import load_config
        from canvodpy.workflows.tasks import _day_files, _resolve_date

        reader_format = _READER_FILE_FORMATS.get(self._reader_name)
        if reader_format is None:
            msg = (
                f"FluentWorkflow cannot select files for the reader "
                f"{self._reader_name!r}; use one of {sorted(_READER_FILE_FORMATS)}"
            )
            raise ValueError(msg)
        site_cfg = load_config().sites.sites[self._site.name]
        day_files = _day_files(
            self._site.name, site_cfg, _resolve_date(date), reader_format
        )

        for name in receiver_list:
            files = day_files[name]
            if not files:
                log.warning("no_files", receiver=name)
                continue
            log.info("files_discovered", receiver=name, n_files=len(files))

            datasets_for_recv = []
            for file in files:
                reader_obj = ReaderFactory.create(self._reader_name, fpath=file.path)
                ds = reader_obj.to_ds(write_global_attrs=True)

                # Filter variables
                if self._keep_vars:
                    drop = [v for v in ds.data_vars if v not in set(self._keep_vars)]
                    if drop:
                        ds = ds.drop_vars(drop)

                datasets_for_recv.append(ds)

            if datasets_for_recv:
                self._datasets[name] = _concat_epoch_datasets(datasets_for_recv)
                log.info("read_complete", receiver=name, files=len(datasets_for_recv))

        return self  # never reached (decorator returns self), but aids type checkers

    @step
    def preprocess(self, agency: str = "COD") -> FluentWorkflow:
        """Apply auxiliary preprocessing to loaded datasets.

        Parameters
        ----------
        agency : str
            Analysis center for auxiliary products (default ``"COD"``).
        """
        log = self.log.bind(agency=agency)

        for name, ds in self._datasets.items():
            try:
                from canvod.auxiliary import preprocess_aux_for_interpolation

                ds = preprocess_aux_for_interpolation(ds)
                self._datasets[name] = ds
                log.info("preprocess_complete", receiver=name)
            except ImportError:
                log.debug("canvod.auxiliary not available, skipping preprocessing")

        return self

    @step
    def augment(
        self,
        source: str = "final",
        agency: str = "COD",
        date: str | None = None,
    ) -> FluentWorkflow:
        """Augment loaded datasets with theta/phi from ephemeris data.

        Parameters
        ----------
        source : str
            Ephemeris source: ``"final"`` (SP3/CLK), ``"rapid"``,
            ``"broadcast"`` (SBF only).
        agency : str
            Analysis center code (default ``"COD"``).
        date : str, optional
            Date in ``YYYYDOY`` format.  If not provided, inferred from
            the most recent ``.read()`` call.
        """
        from canvod.auxiliary.ephemeris.provider import (
            AgencyEphemerisProvider,
        )
        from canvod.config import load_config

        log = self.log.bind(source=source, agency=agency)

        config = load_config()
        site_cfg = config.sites.sites[self._site.name]

        if source in ("final", "rapid"):
            provider = AgencyEphemerisProvider(
                agency=agency,
                product_type=source,
            )
            _date = date or self._last_date
            if _date:
                provider.preprocess_day(_date, site_cfg)

            from canvod.auxiliary.position.position import ECEFPosition

            for name, ds in self._datasets.items():
                try:
                    rx_pos = ECEFPosition.from_ds_metadata(ds)
                except (KeyError, ValueError):  # fmt: skip
                    log.warning(
                        "no_receiver_position",
                        receiver=name,
                    )
                    continue
                self._datasets[name] = provider.augment_dataset(
                    ds,
                    rx_pos,
                )
                log.info("augment_complete", receiver=name)
        else:
            log.warning("augment_source_not_supported", source=source)

        return self

    @step
    def grid(self, kind: str | None = None, **params: Any) -> FluentWorkflow:
        """Build a hemisphere grid and assign cell IDs to all datasets.

        Parameters
        ----------
        kind : str, optional
            Grid type override.  Defaults to the value set at init.
        **params
            Passed to :meth:`GridFactory.create` (e.g.
            ``angular_resolution=5.0``).
        """
        from canvod.grids import add_cell_ids_to_ds_fast

        grid_type = kind or self._grid_type
        builder = GridFactory.create(grid_type, **params)
        self._grid = builder.build()

        for name, ds in self._datasets.items():
            self._datasets[name] = add_cell_ids_to_ds_fast(ds, self._grid, grid_type)

        self.log.info("grid_complete", grid=grid_type, ncells=self._grid.ncells)
        return self

    @step
    def vod(self, canopy: str, reference: str) -> FluentWorkflow:
        """Compute vegetation optical depth for a receiver pair.

        Parameters
        ----------
        canopy : str
            Canopy receiver name (e.g. ``"canopy_01"``).
        reference : str
            Sky/reference receiver name (e.g. ``"reference_01"``).
        """
        canopy_ds = self._datasets[canopy]
        ref_ds = self._datasets[reference]

        calculator = VODFactory.create(
            self._vod_calculator_name,
            canopy_ds=canopy_ds,
            sky_ds=ref_ds,
        )
        self._vod_result = calculator.calculate_vod()
        self._vod_pair = (canopy, reference)

        self.log.info("vod_complete", canopy=canopy, reference=reference)
        return self

    # ------------------------------------------------------------------
    # Terminals (trigger execution)
    # ------------------------------------------------------------------

    @terminal
    def result(self) -> xr.Dataset | dict[str, xr.Dataset]:
        """Execute the plan and return the final data.

        Returns the VOD dataset if a ``.vod()`` step was included,
        otherwise returns the dict of per-receiver datasets.
        """
        if self._vod_result is not None:
            return self._vod_result
        return dict(self._datasets)

    @terminal
    def to_store(self) -> FluentWorkflow:
        """Execute the plan and write results to Icechunk storage.

        Takes the same step first as ``canvodpy run``: a new store gets
        its metadata from the settings, and receivers or VOD analyses the
        store's metadata doesn't list are refused. VOD goes to the group
        ``{calculator}/{analysis}`` of the VOD analysis of the settings that
        pairs the ``.vod()`` receivers, as ``site.vod`` writes it.

        Raises
        ------
        ValueError
            If no VOD analysis of the settings pairs the ``.vod()``
            receivers, or the store refuses the write (names the command
            to run).
        """
        research_site = self._site._site
        if self._vod_result is not None:
            analysis = self._vod_analysis()
            self.log.info("to_store_vod", analysis=analysis)
            research_site.ensure_store_metadata(
                "vod_store", [analysis], self._vod_calculator_name
            )
            self._site.vod_store.write_or_append_group(
                self._vod_result, f"{self._vod_calculator_name}/{analysis}"
            )
        else:
            research_site.ensure_store_metadata(
                "gnss_store", list(self._datasets), self._reader_name
            )
            for name, ds in self._datasets.items():
                self.log.info("to_store_dataset", receiver=name)
                self._site.gnss_store.write_or_append_group(ds, name)
        return self

    def _vod_analysis(self) -> str:
        """The VOD analysis of the settings that pairs the .vod() receivers."""
        canopy, reference = self._vod_pair or (None, None)
        for name, analysis in self._site.vod_analyses.items():
            if (analysis.canopy_receiver, analysis.reference_receiver) == (
                canopy,
                reference,
            ):
                return name
        msg = (
            f"No VOD analysis in the settings pairs {canopy!r} with "
            f"{reference!r} (sites.{self._site.name}.vod_analyses); add one "
            "to store this VOD."
        )
        raise ValueError(msg)

    @terminal
    def plot(self) -> Any:
        """Execute the plan and visualize the result."""
        from canvod.viz import HemisphereVisualizer

        viz = HemisphereVisualizer(self._grid)
        return viz.plot_2d()

    # ------------------------------------------------------------------
    # Plan inspection (does NOT execute)
    # ------------------------------------------------------------------

    def explain(self) -> list[dict[str, Any]]:
        """Return a description of the recorded plan without executing it.

        Returns
        -------
        list[dict]
            One entry per step with keys ``"step"``, ``"args"``, and
            ``"kwargs"``.
        """
        return [
            {"step": fn.__name__, "args": args, "kwargs": kwargs}
            for fn, args, kwargs in self._plan
        ]

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        n = len(self._plan)
        return f"FluentWorkflow(site={self._site.name!r}, pending_steps={n})"
