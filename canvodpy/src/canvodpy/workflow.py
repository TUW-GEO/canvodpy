"""
VOD workflow orchestration using component factories.

.. deprecated::
    ``VODWorkflow`` is deprecated and its ``_augment_data`` step is a
    no-op stub — it never applies ephemeris augmentation, so VOD
    computed through this class uses un-augmented angles. Use
    ``Site(site).pipeline()`` to process data and ``Site(site).vod``
    to compute VOD. Removed with the next major version.
    ``VODWorkflow`` emits a ``FutureWarning`` on instantiation.

Provides high-level workflow coordination with structured logging and
extensibility through factory pattern.

Examples
--------
Basic workflow:

    >>> from canvodpy import VODWorkflow
    >>> workflow = VODWorkflow(site="ExampleSite")
    >>> result = workflow.process_date("2025001")

With custom components:

    >>> workflow = VODWorkflow(
    ...     site="ExampleSite",
    ...     grid="equal_area",
    ...     grid_params={"angular_resolution": 5.0},
    ... )
    >>> vod = workflow.calculate_vod("canopy_01", "reference_01", "2025001")

Debug logging:

    >>> workflow = VODWorkflow(site="ExampleSite", log_level="DEBUG")
    >>> # All logs include site="ExampleSite" context
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog
import xarray as xr

from canvod.utils.tools import deprecated
from canvodpy.api import Site
from canvodpy.factories import GridFactory, ReaderFactory, VODFactory

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger


@deprecated(
    "VODWorkflow is left over from development and will be removed with the next major version. "
    "It never augments the data, so its VOD uses un-augmented angles. "
    "Use canvodpy.Site(<site>).pipeline() to process data and "
    "canvodpy.Site(<site>).vod to compute VOD instead."
)
class VODWorkflow:
    """
    Orchestrate complete VOD analysis workflow.

    Uses component factories for extensibility and structured logging
    for LLM-assisted debugging. Replaces legacy Site + Pipeline pattern.

    Parameters
    ----------
    site : str or Site
        Site name or Site object
    reader : str, default="rinex3"
        Registered reader name
    grid : str, default="equal_area"
        Registered grid name
    vod_calculator : str, default="tau_omega"
        Registered VOD calculator name
    grid_params : dict, optional
        Parameters for grid creation (angular_resolution, cutoff_theta)
    keep_vars : list[str], optional
        RINEX variables to keep. Defaults to KEEP_RNX_VARS.
    log_level : str, default="INFO"
        Logging level (DEBUG, INFO, WARNING, ERROR)

    Attributes
    ----------
    site : Site
        Site configuration
    grid : GridData
        Hemisphere grid structure
    log : BoundLogger
        Structured logger with site context

    Examples
    --------
    Process one date:

        >>> workflow = VODWorkflow(site="ExampleSite")
        >>> data = workflow.process_date("2025001")
        >>> print(data.keys())
        dict_keys(['canopy_01', 'reference_01'])

    Calculate VOD:

        >>> vod = workflow.calculate_vod(
        ...     "canopy_01", "reference_01", "2025001"
        ... )
        >>> print(vod.VOD.mean().item())
        0.42

    Custom grid:

        >>> workflow = VODWorkflow(
        ...     site="ExampleSite",
        ...     grid="equal_area",
        ...     grid_params={"angular_resolution": 5.0},
        ... )

    Notes
    -----
    Preserves logical flow from legacy API:
    Site → Pipeline → process_date → load → augment → grid → calculate
    """

    def __init__(
        self,
        site: str | Site,
        reader: str = "rinex3",
        grid: str = "equal_area",
        vod_calculator: str = "tau_omega",
        grid_params: dict[str, Any] | None = None,
        keep_vars: list[str] | None = None,
        log_level: str = "INFO",
    ) -> None:
        """Initialize workflow with component factories."""
        # Handle site input
        site_name = site if isinstance(site, str) else site.name
        self.site = Site(site) if isinstance(site, str) else site

        # Setup logging with site context
        self.log: BoundLogger = structlog.get_logger(__name__).bind(site=site_name)

        # Store configuration
        self.reader_name = reader
        self.grid_name = grid
        self.vod_calculator_name = vod_calculator
        if keep_vars is None:
            from canvod.config import load_config

            keep_vars = load_config().processing.params.keep_gnss_observables
        self.keep_vars = keep_vars

        # Create grid using factory (cached for workflow)
        grid_params = grid_params or {}
        builder = GridFactory.create(grid, **grid_params)
        self.grid = builder.build()

        self.log.info(
            "workflow_initialized",
            grid=grid,
            reader=reader,
            calculator=vod_calculator,
            ncells=self.grid.ncells,
        )

    def process_date(
        self,
        date: str,
        receivers: list[str] | None = None,
    ) -> dict[str, xr.Dataset]:
        """
        Process RINEX data for one date.

        Workflow: load_rinex → augment → assign_grid → store

        Parameters
        ----------
        date : str
            Date in YYYYDOY format (e.g., "2025001" = Jan 1, 2025)
        receivers : list[str], optional
            Receiver names to process. If None, use all active receivers.

        Returns
        -------
        dict[str, xr.Dataset]
            Processed datasets keyed by receiver name. Each dataset has
            cell assignments and filtered data.

        Examples
        --------
        >>> workflow = VODWorkflow("ExampleSite")
        >>> data = workflow.process_date("2025001")
        >>> canopy = data["canopy_01"]
        >>> print(canopy.sizes)
        {'epoch': 2880, 'sv': 32, 'cell': 324}

        Process specific receivers:

        >>> data = workflow.process_date(
        ...     "2025001",
        ...     receivers=["canopy_01"]
        ... )

        Notes
        -----
        This is the main entry point for data processing. Orchestrates
        the full pipeline from raw RINEX to grid-assigned observations.
        """
        log = self.log.bind(date=date)
        log.info("process_date_started")

        # Get receivers to process
        receiver_list = receivers or list(self.site.active_receivers.keys())
        results = {}

        for recv_name in receiver_list:
            recv_log = log.bind(receiver=recv_name)
            recv_log.info("processing_receiver")

            try:
                # Step 1: Load RINEX
                ds = self._load_rinex(recv_name, date, recv_log)

                # Step 2: Augment (preprocessing)
                ds = self._augment_data(ds, recv_log)

                # Step 3: Assign grid cells
                ds = self._assign_grid_cells(ds, recv_log)

                results[recv_name] = ds
                recv_log.info(
                    "processing_complete",
                    variables=list(ds.data_vars),
                    cells=ds.sizes.get("cell", 0),
                )

            except Exception as e:
                recv_log.error("processing_failed", error=str(e), exc_info=True)
                raise

        log.info("process_date_complete", receivers=len(results))
        return results

    def calculate_vod(
        self,
        canopy_receiver: str,
        sky_receiver: str,
        date: str,
        use_cached: bool = True,
    ) -> xr.Dataset:
        """
        Calculate VOD from canopy and sky receivers.

        Parameters
        ----------
        canopy_receiver : str
            Receiver under canopy (e.g., "canopy_01")
        sky_receiver : str
            Sky reference receiver (e.g., "reference_01")
        date : str
            Date in YYYYDOY format
        use_cached : bool, default=True
            If True, reuse datasets from process_date cache

        Returns
        -------
        xr.Dataset
            VOD dataset with variables:
            - VOD : Vegetation Optical Depth
            - phi : Azimuth angles
            - theta : Elevation angles

        Examples
        --------
        >>> workflow = VODWorkflow("ExampleSite")
        >>> vod = workflow.calculate_vod(
        ...     "canopy_01", "reference_01", "2025001"
        ... )
        >>> print(vod.VOD.mean().item())
        0.42

        Without caching:

        >>> vod = workflow.calculate_vod(
        ...     "canopy_01",
        ...     "reference_01",
        ...     "2025001",
        ...     use_cached=False,
        ... )

        Notes
        -----
        Uses VODFactory to create calculator. Supports community
        extensions via factory registration.
        """
        log = self.log.bind(date=date, canopy=canopy_receiver, sky=sky_receiver)
        log.info("calculate_vod_started")

        # Load or retrieve datasets
        if use_cached and hasattr(self, "_dataset_cache"):
            dataset_cache = cast(dict[str, xr.Dataset], self._dataset_cache)
            canopy_ds = dataset_cache.get(canopy_receiver)
            sky_ds = dataset_cache.get(sky_receiver)
        else:
            canopy_ds = None
            sky_ds = None

        # Process if not cached
        if canopy_ds is None:
            log.debug("loading_canopy")
            data = self.process_date(date, receivers=[canopy_receiver])
            canopy_ds = data[canopy_receiver]

        if sky_ds is None:
            log.debug("loading_sky")
            data = self.process_date(date, receivers=[sky_receiver])
            sky_ds = data[sky_receiver]

        # Use factory to create calculator
        calculator = VODFactory.create(
            self.vod_calculator_name,
            canopy_ds=canopy_ds,
            sky_ds=sky_ds,
        )

        # Calculate VOD
        vod_ds = calculator.calculate_vod()

        log.info(
            "calculate_vod_complete",
            cells=vod_ds.sizes.get("cell", 0) if "cell" in vod_ds.sizes else 0,
            vod_mean=float(vod_ds.VOD.mean().compute().item())
            if "VOD" in vod_ds
            else None,
        )
        return vod_ds

    def _load_rinex(self, receiver: str, date: str, log: BoundLogger) -> xr.Dataset:
        """
        Load RINEX using factory.

        Parameters
        ----------
        receiver : str
            Receiver name
        date : str
            Date in YYYYDOY format
        log : BoundLogger
            Logger with receiver context

        Returns
        -------
        xr.Dataset
            RINEX data

        Notes
        -----
        Uses ReaderFactory to create reader instance.
        """
        log.debug("load_rinex_started")

        # Get file path from site config
        rinex_path = self._get_rinex_path(receiver, date)

        # Create reader using factory
        reader = ReaderFactory.create(
            self.reader_name,
            fpath=rinex_path,
        )

        # Read data
        ds = reader.to_ds()

        # Filter variables
        if self.keep_vars:
            keep_vars_set = set(self.keep_vars)
            drop_vars = [v for v in ds.data_vars if v not in keep_vars_set]
            if drop_vars:
                ds = ds.drop_vars(drop_vars)

        log.debug("load_rinex_complete", variables=list(ds.data_vars))
        return ds

    def _augment_data(self, ds: xr.Dataset, log: BoundLogger) -> xr.Dataset:
        """
        Apply augmentation steps.

        Parameters
        ----------
        ds : xr.Dataset
            Input dataset
        log : BoundLogger
            Logger with context

        Returns
        -------
        xr.Dataset
            Augmented dataset

        Notes
        -----
        Passes the data through unchanged. Preprocessing is done by
        ``canvod.ops`` (``Op`` / ``Pipeline``) in ``canvodpy run``.
        """
        log.debug("augment_data_started")
        log.debug("augment_data_complete")
        return ds

    def _assign_grid_cells(self, ds: xr.Dataset, log: BoundLogger) -> xr.Dataset:
        """
        Assign grid cells to observations.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset with phi, theta coordinates
        log : BoundLogger
            Logger with context

        Returns
        -------
        xr.Dataset
            Dataset with added 'cell' coordinate

        Notes
        -----
        Uses grid operations from canvod.grids package.
        """
        log.debug("assign_grid_cells_started")

        # Use grid operations
        from canvod.grids import add_cell_ids_to_ds_fast

        ds_with_cells = add_cell_ids_to_ds_fast(ds, self.grid, self.grid_name)

        log.debug(
            "assign_grid_cells_complete",
            cells=ds_with_cells.sizes.get("cell", 0),
        )
        return ds_with_cells

    def _get_rinex_path(self, receiver: str, date: str) -> Path:
        """
        Get RINEX file path from site configuration.

        Parameters
        ----------
        receiver : str
            Receiver name
        date : str
            Date in YYYYDOY format

        Returns
        -------
        Path
            Path to RINEX file

        Raises
        ------
        ValueError
            If receiver not found in site configuration
        """
        if receiver not in self.site.receivers:
            available = list(self.site.receivers.keys())
            msg = f"Receiver '{receiver}' not in site. Available: {available}"
            raise ValueError(msg)

        # Use internal site object to get path
        site_impl = cast(Any, self.site._site)
        return cast(Path, site_impl.get_rinex_path(receiver, date))

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"VODWorkflow(site='{self.site.name}', "
            f"grid='{self.grid_name}', reader='{self.reader_name}')"
        )
