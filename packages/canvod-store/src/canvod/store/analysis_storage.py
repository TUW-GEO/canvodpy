"""Persistent storage for precomputed analysis results via Icechunk.

Stores dataset+grid-specific analysis outputs in an Icechunk repository
under ``metadata/{dataset_name}/{grid_name}/``:

* **weights** – per-cell weight arrays (``ncells,``).
* **filter_masks** – per-observation statistical masks (``epoch × sid``).
* **spatial_masks** – per-cell geometric selection masks (``ncells,``).
* **statistics** – per-cell aggregated statistics (``ncells,``).

Classes
-------
``AnalysisStorage``
    Read / write / delete analysis metadata for a single Icechunk store.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import structlog
import xarray as xr
from canvod.store_metadata.io import commit_with_rebase

from canvod.store.store import MyIcechunkStore

logger = structlog.get_logger(__name__)


def _clean_attrs(attrs: dict) -> dict:
    """Convert numpy/non-JSON types to Python builtins for Zarr compatibility."""
    clean: dict = {}
    for k, v in attrs.items():
        if hasattr(v, "item"):  # numpy scalar
            clean[k] = v.item()
        elif isinstance(v, dict):
            clean[k] = _clean_attrs(v)
        elif isinstance(v, (list, tuple)):
            clean[k] = [x.item() if hasattr(x, "item") else x for x in v]
        else:
            clean[k] = v
    return clean


class AnalysisStorage:
    """Manage persistent storage of analysis results for dataset+grid pairs.

    Storage layout inside the Icechunk repository::

        metadata/{dataset_name}/{grid_name}/
        ├── weights/              # (ncells,)
        │   ├── observation_count
        │   ├── solid_angle
        │   └── combined
        ├── filter_masks/         # (epoch, sid)
        │   ├── mask_iqr
        │   └── mask_zscore
        ├── spatial_masks/        # (ncells,)
        │   ├── mask_north
        │   └── mask_high_elevation
        └── statistics/           # (ncells,)
            ├── obs_count
            ├── mean_vod
            └── std_vod

    Parameters
    ----------
    store_path : Path or str
        Path to the VOD Icechunk store directory.

    """

    def __init__(self, store_path: Path | str) -> None:
        """Initialize the storage manager.

        Parameters
        ----------
        store_path : Path | str
            Path to the VOD Icechunk store directory.

        """
        self.store_path = Path(store_path)
        self.store = MyIcechunkStore(self.store_path)

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.

        """
        return f"AnalysisStorage(store_path={self.store_path})"

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------

    def store_weights(
        self,
        dataset_name: str,
        grid_name: str,
        weights: dict[str, np.ndarray],
        weight_params: dict[str, dict] | None = None,
        overwrite: bool = False,
    ) -> str:
        """Store per-cell weight arrays.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier (e.g. ``'reference_01_canopy_01'``).
        grid_name : str
            Grid identifier (e.g. ``'equal_area_2deg'``).
        weights : dict
            ``{name: array}`` – all arrays must have shape ``(ncells,)``.
        weight_params : dict, optional
            Parameters used to compute each weight type.
        overwrite : bool
            Overwrite existing weights.

        Returns
        -------
        str
            Icechunk snapshot ID.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/weights"
        logger.info("Storing weights to %s", group_path)

        # Validate shapes
        ncells = len(next(iter(weights.values())))
        for name, arr in weights.items():
            if arr.shape != (ncells,):
                raise ValueError(
                    f"Weight '{name}' has shape {arr.shape}, expected ({ncells},)"
                )

        # Build xarray dataset
        weight_vars = {
            name: (["cell"], arr.astype(np.float32)) for name, arr in weights.items()
        }
        ds_weights = xr.Dataset(
            weight_vars, coords={"cell": np.arange(ncells, dtype=np.int32)}
        )

        attrs: dict[str, Any] = {
            "created_at": datetime.now().isoformat(),
            "dataset": dataset_name,
            "grid": grid_name,
            "weight_types": list(weights.keys()),
            "ncells": ncells,
        }
        if weight_params:
            attrs["weight_parameters"] = str(weight_params)
        ds_weights.attrs.update(attrs)

        # Persist
        with self.store.writable_session() as session:
            from icechunk.xarray import to_icechunk

            mode = "w" if overwrite else "w-"
            to_icechunk(ds_weights, session, group=group_path, mode=mode)
            snapshot_id: str = commit_with_rebase(
                session,
                f"Stored weights for {dataset_name}/{grid_name}",
                store_path=self.store_path,
            )

        logger.info("Weights stored (snapshot: %s)", snapshot_id[:8])
        return snapshot_id

    def load_weights(
        self,
        dataset_name: str,
        grid_name: str,
        weight_type: str | None = None,
    ) -> dict[str, np.ndarray]:
        """Load stored weight arrays.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        weight_type : str, optional
            Load only this weight.  ``None`` loads all.

        Returns
        -------
        dict
            ``{name: ndarray}`` of loaded weights.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/weights"

        try:
            with self.store.readonly_session() as session:
                ds_weights = xr.open_zarr(
                    session.store, group=group_path, consolidated=False
                )

            if weight_type:
                if weight_type not in ds_weights:
                    raise ValueError(
                        f"Weight '{weight_type}' not found. "
                        f"Available: {list(ds_weights.data_vars)}"
                    )
                return {weight_type: ds_weights[weight_type].values}
            return {var: ds_weights[var].values for var in ds_weights.data_vars}

        except Exception:
            logger.error("Failed to load weights from %s", group_path, exc_info=True)
            raise

    def has_weights(self, dataset_name: str, grid_name: str) -> bool:
        """Return ``True`` if weights exist for the dataset+grid pair."""
        try:
            self.load_weights(dataset_name, grid_name)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Filter masks (per observation)
    # ------------------------------------------------------------------

    def store_filter_masks(
        self,
        dataset_name: str,
        grid_name: str,
        masks: dict[str, xr.DataArray],
        filter_params: dict[str, dict] | None = None,
        overwrite: bool = False,
    ) -> str:
        """Store per-observation filter masks at native resolution.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        masks : dict
            ``{filter_name: DataArray}`` – all must share the same
            ``(epoch, sid)`` shape.
        filter_params : dict, optional
            Parameters used for each filter.
        overwrite : bool
            Overwrite existing masks.

        Returns
        -------
        str
            Icechunk snapshot ID.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/filter_masks"
        logger.info("Storing filter masks to %s", group_path)

        first_mask = next(iter(masks.values()))
        shape = first_mask.shape

        mask_vars: dict[str, xr.DataArray] = {}
        for name, mask_array in masks.items():
            if not isinstance(mask_array, xr.DataArray):
                raise TypeError(f"Mask '{name}' must be xr.DataArray")
            if mask_array.shape != shape:
                raise ValueError("All masks must have same shape")
            mask_vars[f"mask_{name}"] = mask_array.astype(np.int8)

        ds_masks = xr.Dataset(mask_vars)

        attrs: dict[str, Any] = {
            "created_at": datetime.now().isoformat(),
            "dataset": dataset_name,
            "grid": grid_name,
            "filter_types": list(masks.keys()),
            "shape": str(shape),
            "coordinate_source": f"/{dataset_name}/",
        }
        if filter_params:
            attrs["filter_parameters"] = str(filter_params)
        ds_masks.attrs.update(attrs)

        # Rechunk for efficient columnar storage
        logger.info("Rechunking masks for efficient storage")
        ds_masks = ds_masks.chunk({"epoch": 10000, "sid": -1})

        with self.store.writable_session() as session:
            import dask
            from icechunk.xarray import to_icechunk

            logger.info("Writing masks (this may take a few minutes)")
            with dask.config.set(scheduler="threads", num_workers=4):
                mode = "w" if overwrite else "w-"
                to_icechunk(ds_masks, session, group=group_path, mode=mode)

            logger.info("Committing")
            snapshot_id = commit_with_rebase(
                session,
                f"Stored filter masks for {dataset_name}/{grid_name}",
                store_path=self.store_path,
            )

        logger.info("Filter masks stored (snapshot: %s)", snapshot_id[:8])
        return snapshot_id

    def load_filter_mask(
        self,
        dataset_name: str,
        grid_name: str,
        filter_type: str,
        attach_coords: bool = True,
    ) -> xr.DataArray:
        """Load a single filter mask.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        filter_type : str
            Filter name (e.g. ``'iqr'``, ``'zscore'``).
        attach_coords : bool
            Re-attach ``epoch`` / ``sid`` coordinates from the source
            dataset group.  Set ``False`` for faster loading when
            coordinates are not needed.

        Returns
        -------
        xr.DataArray
            Boolean mask with shape ``(epoch, sid)``.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/filter_masks"

        try:
            with self.store.readonly_session() as session:
                ds_masks = xr.open_zarr(
                    session.store, group=group_path, consolidated=False
                )

            mask_var = f"mask_{filter_type}"
            if mask_var not in ds_masks:
                available = [v.replace("mask_", "") for v in ds_masks.data_vars]
                raise ValueError(
                    f"Filter mask '{filter_type}' not found. Available: {available}"
                )

            mask = ds_masks[mask_var].astype(bool)

            if attach_coords:
                coord_source = ds_masks.attrs.get(
                    "coordinate_source", f"/{dataset_name}/"
                )
                with self.store.readonly_session() as session:
                    ds_source = xr.open_zarr(
                        session.store,
                        group=coord_source.strip("/"),
                        consolidated=False,
                    )

                mask = mask.assign_coords(
                    {"epoch": ds_source["epoch"], "sid": ds_source["sid"]}
                )
                for coord in [
                    "band",
                    "code",
                    "sv",
                    "system",
                    "freq_min",
                    "freq_max",
                    "freq_center",
                ]:
                    if coord in ds_source.coords:
                        mask = mask.assign_coords({coord: ds_source[coord]})

            return mask

        except Exception:
            logger.error("Failed to load filter mask", exc_info=True)
            raise

    def load_all_filter_masks(
        self, dataset_name: str, grid_name: str
    ) -> dict[str, xr.DataArray]:
        """Load all stored filter masks.

        Returns
        -------
        dict
            ``{filter_name: DataArray}`` – boolean masks.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/filter_masks"

        try:
            with self.store.readonly_session() as session:
                ds_masks = xr.open_zarr(
                    session.store, group=group_path, consolidated=False
                )
            return {
                var.replace("mask_", ""): ds_masks[var].astype(bool)
                for var in ds_masks.data_vars
            }
        except Exception:
            logger.error(
                "Failed to load filter masks from %s", group_path, exc_info=True
            )
            raise

    def has_filter_masks(self, dataset_name: str, grid_name: str) -> bool:
        """Return ``True`` if filter masks exist for the dataset+grid pair."""
        try:
            self.load_all_filter_masks(dataset_name, grid_name)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Spatial masks (per cell)
    # ------------------------------------------------------------------

    def store_spatial_masks(
        self,
        dataset_name: str,
        grid_name: str,
        masks: dict[str, np.ndarray],
        mask_descriptions: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> str:
        """Store per-cell geometric selection masks.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        masks : dict
            ``{name: bool_array}`` – all arrays must have shape ``(ncells,)``
            and boolean dtype.
        mask_descriptions : dict, optional
            Human-readable description for each mask (stored as variable attrs).
        overwrite : bool
            Overwrite existing masks.

        Returns
        -------
        str
            Icechunk snapshot ID.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/spatial_masks"
        logger.info("Storing spatial masks to %s", group_path)

        ncells = len(next(iter(masks.values())))
        for name, arr in masks.items():
            if arr.shape != (ncells,):
                raise ValueError(
                    f"Mask '{name}' has shape {arr.shape}, expected ({ncells},)"
                )
            if arr.dtype != bool:
                raise ValueError(
                    f"Mask '{name}' must be boolean dtype, got {arr.dtype}"
                )

        mask_vars = {
            f"mask_{name}": (["cell"], arr.astype(np.int8))
            for name, arr in masks.items()
        }
        ds_masks = xr.Dataset(
            mask_vars, coords={"cell": np.arange(ncells, dtype=np.int32)}
        )

        # Per-variable metadata
        for name, arr in masks.items():
            n_sel = int(arr.sum())
            ds_masks[f"mask_{name}"].attrs["n_cells_selected"] = n_sel
            ds_masks[f"mask_{name}"].attrs["fraction_selected"] = float(n_sel / ncells)
        if mask_descriptions:
            for name, desc in mask_descriptions.items():
                if name in masks:
                    ds_masks[f"mask_{name}"].attrs["description"] = desc

        ds_masks.attrs.update(
            {
                "created_at": datetime.now().isoformat(),
                "dataset": dataset_name,
                "grid": grid_name,
                "mask_types": list(masks.keys()),
                "ncells": ncells,
            }
        )

        with self.store.writable_session() as session:
            from icechunk.xarray import to_icechunk

            mode = "w" if overwrite else "w-"
            to_icechunk(ds_masks, session, group=group_path, mode=mode)
            snapshot_id = commit_with_rebase(
                session,
                f"Stored spatial masks for {dataset_name}/{grid_name}",
                store_path=self.store_path,
            )

        logger.info("Spatial masks stored (snapshot: %s)", snapshot_id[:8])
        return snapshot_id

    def load_spatial_mask(
        self, dataset_name: str, grid_name: str, mask_name: str
    ) -> np.ndarray:
        """Load a single spatial mask.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        mask_name : str
            Mask name (e.g. ``'north'``, ``'high_elevation'``).

        Returns
        -------
        np.ndarray
            Boolean array with shape ``(ncells,)``.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/spatial_masks"

        try:
            with self.store.readonly_session() as session:
                ds_masks = xr.open_zarr(
                    session.store, group=group_path, consolidated=False
                )

            mask_var = f"mask_{mask_name}"
            if mask_var not in ds_masks:
                available = [v.replace("mask_", "") for v in ds_masks.data_vars]
                raise ValueError(
                    f"Spatial mask '{mask_name}' not found. Available: {available}"
                )
            return ds_masks[mask_var].values.astype(bool)

        except Exception:
            logger.error(
                "Failed to load spatial mask from %s", group_path, exc_info=True
            )
            raise

    def load_all_spatial_masks(
        self, dataset_name: str, grid_name: str
    ) -> dict[str, np.ndarray]:
        """Load all spatial masks.

        Returns
        -------
        dict
            ``{name: bool_ndarray}``.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/spatial_masks"

        try:
            with self.store.readonly_session() as session:
                ds_masks = xr.open_zarr(
                    session.store, group=group_path, consolidated=False
                )
            return {
                var.replace("mask_", ""): ds_masks[var].values.astype(bool)
                for var in ds_masks.data_vars
            }
        except Exception:
            logger.error(
                "Failed to load spatial masks from %s", group_path, exc_info=True
            )
            raise

    def has_spatial_masks(self, dataset_name: str, grid_name: str) -> bool:
        """Return ``True`` if spatial masks exist for the dataset+grid pair."""
        try:
            self.load_all_spatial_masks(dataset_name, grid_name)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def store_statistics(
        self,
        dataset_name: str,
        grid_name: str,
        stats: dict[str, np.ndarray],
        overwrite: bool = False,
    ) -> str:
        """Store pre-computed per-cell statistics.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        stats : dict
            ``{name: array}`` – all arrays must have shape ``(ncells,)``.
            Variables whose name ends with ``'_count'`` or equals
            ``'obs_count'`` are stored as ``int64``; everything else as
            ``float32``.
        overwrite : bool
            Overwrite existing statistics.

        Returns
        -------
        str
            Icechunk snapshot ID.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/statistics"
        logger.info("Storing statistics to %s", group_path)

        ncells = len(next(iter(stats.values())))
        for name, arr in stats.items():
            if arr.shape != (ncells,):
                raise ValueError(
                    f"Statistic '{name}' has shape {arr.shape}, expected ({ncells},)"
                )

        stat_vars = {}
        for name, arr in stats.items():
            dtype = (
                np.int64
                if (name.endswith("_count") or name == "obs_count")
                else np.float32
            )
            stat_vars[name] = (["cell"], arr.astype(dtype))

        ds_stats = xr.Dataset(
            stat_vars, coords={"cell": np.arange(ncells, dtype=np.int32)}
        )

        # Summary statistics per variable (stored as variable attrs)
        for name, arr in stats.items():
            valid = np.isfinite(arr)
            if np.any(valid):
                ds_stats[name].attrs.update(
                    {
                        "min": float(np.nanmin(arr)),
                        "max": float(np.nanmax(arr)),
                        "mean": float(np.nanmean(arr)),
                        "n_valid": int(np.sum(valid)),
                    }
                )

        ds_stats.attrs.update(
            {
                "created_at": datetime.now().isoformat(),
                "dataset": dataset_name,
                "grid": grid_name,
                "statistics": list(stats.keys()),
                "ncells": ncells,
            }
        )

        with self.store.writable_session() as session:
            from icechunk.xarray import to_icechunk

            mode = "w" if overwrite else "w-"
            to_icechunk(ds_stats, session, group=group_path, mode=mode)
            snapshot_id = commit_with_rebase(
                session,
                f"Stored statistics for {dataset_name}/{grid_name}",
                store_path=self.store_path,
            )

        logger.info("Statistics stored (snapshot: %s)", snapshot_id[:8])
        return snapshot_id

    def load_statistics(
        self,
        dataset_name: str,
        grid_name: str,
        stat_name: str | None = None,
    ) -> dict[str, np.ndarray]:
        """Load pre-computed per-cell statistics.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        stat_name : str, optional
            Load only this statistic.  ``None`` loads all.

        Returns
        -------
        dict
            ``{name: ndarray}``.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/statistics"

        try:
            with self.store.readonly_session() as session:
                ds_stats = xr.open_zarr(
                    session.store, group=group_path, consolidated=False
                )

            if stat_name:
                if stat_name not in ds_stats:
                    raise ValueError(
                        f"Statistic '{stat_name}' not found. "
                        f"Available: {list(ds_stats.data_vars)}"
                    )
                return {stat_name: ds_stats[stat_name].values}
            return {var: ds_stats[var].values for var in ds_stats.data_vars}

        except Exception:
            logger.error("Failed to load statistics from %s", group_path, exc_info=True)
            raise

    def has_statistics(self, dataset_name: str, grid_name: str) -> bool:
        """Return ``True`` if statistics exist for the dataset+grid pair."""
        try:
            self.load_statistics(dataset_name, grid_name)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def list_available_metadata(
        self, dataset_name: str, grid_name: str
    ) -> dict[str, bool]:
        """Check which metadata categories are stored.

        Returns
        -------
        dict
            ``{category: bool}`` for weights, filter_masks, spatial_masks,
            statistics.

        """
        return {
            "weights": self.has_weights(dataset_name, grid_name),
            "filter_masks": self.has_filter_masks(dataset_name, grid_name),
            "spatial_masks": self.has_spatial_masks(dataset_name, grid_name),
            "statistics": self.has_statistics(dataset_name, grid_name),
        }

    def get_metadata_summary(self, dataset_name: str, grid_name: str) -> dict[str, Any]:
        """Detailed summary of all stored metadata for a dataset+grid pair.

        Returns
        -------
        dict
            Nested summary with availability flags and per-category details.

        """
        summary: dict[str, Any] = {
            "dataset": dataset_name,
            "grid": grid_name,
            "available": self.list_available_metadata(dataset_name, grid_name),
        }

        if summary["available"]["weights"]:
            weights = self.load_weights(dataset_name, grid_name)
            summary["weights"] = {
                "types": list(weights.keys()),
                "ncells": len(next(iter(weights.values()))),
            }

        if summary["available"]["filter_masks"]:
            masks = self.load_all_filter_masks(dataset_name, grid_name)
            summary["filter_masks"] = {
                "types": list(masks.keys()),
                "shape": next(iter(masks.values())).shape,
            }

        if summary["available"]["spatial_masks"]:
            masks = self.load_all_spatial_masks(dataset_name, grid_name)
            summary["spatial_masks"] = {
                "types": list(masks.keys()),
                "ncells": len(next(iter(masks.values()))),
            }

        if summary["available"]["statistics"]:
            stats = self.load_statistics(dataset_name, grid_name)
            summary["statistics"] = {
                "types": list(stats.keys()),
                "ncells": len(next(iter(stats.values()))),
            }

        return summary

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def _delete_group(self, group_path: str, label: str) -> str:
        """Generic group deletion helper.

        Parameters
        ----------
        group_path : str
            Zarr group path inside the store.
        label : str
            Human-readable label for log / commit messages.

        Returns
        -------
        str
            Snapshot ID.

        Raises
        ------
        ValueError
            If the group does not exist.

        """
        logger.info("Deleting %s at %s", label, group_path)

        with self.store.writable_session() as session:
            import zarr

            store: Any = zarr.open(session.store, mode="r+")
            if group_path in store:
                del store[group_path]
                snapshot_id = commit_with_rebase(
                    session, f"Deleted {label}", store_path=self.store_path
                )
                logger.info("%s deleted (snapshot: %s)", label, snapshot_id[:8])
                return snapshot_id
            raise ValueError(f"Group {group_path} does not exist")

    def delete_weights(self, dataset_name: str, grid_name: str) -> str:
        """Delete all weights for a dataset+grid pair."""
        return self._delete_group(
            f"metadata/{dataset_name}/{grid_name}/weights",
            f"weights for {dataset_name}/{grid_name}",
        )

    def delete_filter_masks(self, dataset_name: str, grid_name: str) -> str:
        """Delete all filter masks for a dataset+grid pair."""
        return self._delete_group(
            f"metadata/{dataset_name}/{grid_name}/filter_masks",
            f"filter masks for {dataset_name}/{grid_name}",
        )

    def delete_spatial_masks(self, dataset_name: str, grid_name: str) -> str:
        """Delete all spatial masks for a dataset+grid pair."""
        return self._delete_group(
            f"metadata/{dataset_name}/{grid_name}/spatial_masks",
            f"spatial masks for {dataset_name}/{grid_name}",
        )

    def delete_statistics(self, dataset_name: str, grid_name: str) -> str:
        """Delete all statistics for a dataset+grid pair."""
        return self._delete_group(
            f"metadata/{dataset_name}/{grid_name}/statistics",
            f"statistics for {dataset_name}/{grid_name}",
        )

    # ------------------------------------------------------------------
    # Per-cell timeseries
    # ------------------------------------------------------------------

    def store_percell_timeseries(
        self,
        percell_ds: xr.Dataset,
        system: str,
        band: str,
        code: str,
        branch: str = "per_cell",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a per-cell timeseries dataset for a system/band/code combination.

        Parameters
        ----------
        percell_ds : xr.Dataset
            Per-cell timeseries dataset with dims ``(cell, time)``.
        system : str
            GNSS system prefix (e.g. ``'G'``, ``'E'``).
        band : str
            Frequency band (e.g. ``'L1'``, ``'E1'``).
        code : str
            Tracking code (e.g. ``'C'``, ``'L'``).
        branch : str
            Icechunk branch name (default: ``'per_cell'``).
        metadata : dict, optional
            Additional metadata to attach to the dataset.

        Returns
        -------
        str
            Icechunk snapshot ID.

        """
        group_name = f"{system}_{band}_{code}"
        logger.info(
            "Storing per-cell timeseries to group '%s' on branch '%s'",
            group_name,
            branch,
        )

        # Ensure branch exists
        try:
            main_head = next(iter(self.store.repo.ancestry(branch="main"))).id
            self.store.repo.create_branch(
                branch,
                main_head,
            )
        except Exception:
            pass  # Branch already exists

        # Clean attributes for JSON serializability
        ds = percell_ds.copy()
        ds.attrs = _clean_attrs(ds.attrs)
        for var in ds.data_vars:
            ds[var].attrs = _clean_attrs(ds[var].attrs)

        # Add processing metadata
        ds.attrs.update(
            {
                "gnss_system": system,
                "frequency_band": band,
                "signal_code": code,
                "group_name": group_name,
                "data_type": "per_cell_timeseries",
                "created_at": datetime.now().isoformat(),
            }
        )
        if metadata:
            ds.attrs.update(_clean_attrs(metadata))

        # Optimized chunking for per-cell data
        ncells = ds.sizes.get("cell", 1)
        chunks = {"cell": min(1000, ncells), "time": -1}
        ds = ds.chunk(chunks)

        with self.store.writable_session(branch=branch) as session:
            import dask
            from icechunk.xarray import to_icechunk

            with dask.config.set(scheduler="threads", num_workers=4):
                to_icechunk(ds, session, group=group_name, mode="w")
            snapshot_id: str = commit_with_rebase(
                session,
                f"Stored per-cell timeseries for {group_name}",
                store_path=self.store_path,
            )

        logger.info("Per-cell timeseries stored (snapshot: %s)", snapshot_id[:8])
        return snapshot_id

    def load_percell_timeseries(
        self,
        system: str,
        band: str,
        code: str,
        branch: str = "per_cell",
    ) -> xr.Dataset:
        """Load a per-cell timeseries dataset.

        Parameters
        ----------
        system : str
            GNSS system prefix.
        band : str
            Frequency band.
        code : str
            Tracking code.
        branch : str
            Icechunk branch name (default: ``'per_cell'``).

        Returns
        -------
        xr.Dataset
            Per-cell timeseries dataset.

        Raises
        ------
        ValueError
            If the requested group does not exist.

        """
        group_name = f"{system}_{band}_{code}"

        try:
            with self.store.readonly_session(branch=branch) as session:
                return xr.open_zarr(session.store, group=group_name, consolidated=False)
        except Exception as exc:
            available = self.list_percell_datasets(branch=branch)
            raise ValueError(
                f"Per-cell dataset '{group_name}' not found on branch '{branch}'. "
                f"Available: {available}"
            ) from exc

    def list_percell_datasets(self, branch: str = "per_cell") -> list[str]:
        """List all per-cell timeseries datasets in the store.

        Parameters
        ----------
        branch : str
            Icechunk branch name (default: ``'per_cell'``).

        Returns
        -------
        list of str
            Sorted list of group names in ``system_band_code`` format.

        """
        try:
            groups = self.store.list_groups(branch=branch)
            return sorted(groups)
        except Exception:
            logger.debug("No per-cell datasets found on branch '%s'", branch)
            return []

    def has_percell_timeseries(
        self, system: str, band: str, code: str, branch: str = "per_cell"
    ) -> bool:
        """Return ``True`` if a per-cell timeseries exists for the given combination."""
        group_name = f"{system}_{band}_{code}"
        return group_name in self.list_percell_datasets(branch=branch)

    def delete_all_metadata(self, dataset_name: str, grid_name: str) -> str:
        """Delete the entire metadata subtree for a dataset+grid pair."""
        return self._delete_group(
            f"metadata/{dataset_name}/{grid_name}",
            f"all metadata for {dataset_name}/{grid_name}",
        )

    def delete_specific_weight(
        self, dataset_name: str, grid_name: str, weight_name: str
    ) -> str:
        """Delete a single weight variable from an existing weights group.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        weight_name : str
            Weight variable name (e.g. ``'observation_count'``).

        Returns
        -------
        str
            Snapshot ID.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/weights"
        logger.info("Deleting weight '%s' from %s", weight_name, group_path)

        with self.store.writable_session() as session:
            import zarr

            group: Any = zarr.open(session.store, path=group_path, mode="r+")
            if weight_name in group:
                del group[weight_name]
                snapshot_id = commit_with_rebase(
                    session,
                    f"Deleted weight '{weight_name}' for {dataset_name}/{grid_name}",
                    store_path=self.store_path,
                )
                logger.info(
                    "Weight '%s' deleted (snapshot: %s)",
                    weight_name,
                    snapshot_id[:8],
                )
                return snapshot_id
            raise ValueError(f"Weight '{weight_name}' does not exist in {group_path}")

    def delete_specific_filter_mask(
        self, dataset_name: str, grid_name: str, filter_type: str
    ) -> str:
        """Delete a single filter mask variable from an existing filter_masks group.

        Parameters
        ----------
        dataset_name : str
            Dataset identifier.
        grid_name : str
            Grid identifier.
        filter_type : str
            Filter type name (e.g. ``'iqr'``).

        Returns
        -------
        str
            Snapshot ID.

        """
        group_path = f"metadata/{dataset_name}/{grid_name}/filter_masks"
        mask_var = f"mask_{filter_type}"
        logger.info("Deleting filter mask '%s' from %s", filter_type, group_path)

        with self.store.writable_session() as session:
            import zarr

            group: Any = zarr.open(session.store, path=group_path, mode="r+")
            if mask_var in group:
                del group[mask_var]
                commit_msg = (
                    f"Deleted filter mask '{filter_type}' for "
                    f"{dataset_name}/{grid_name}"
                )
                snapshot_id = commit_with_rebase(
                    session, commit_msg, store_path=self.store_path
                )
                logger.info(
                    "Filter mask '%s' deleted (snapshot: %s)",
                    filter_type,
                    snapshot_id[:8],
                )
                return snapshot_id
            raise ValueError(
                f"Filter mask '{filter_type}' does not exist in {group_path}"
            )
