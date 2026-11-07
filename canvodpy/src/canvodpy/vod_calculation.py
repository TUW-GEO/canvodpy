"""The VOD of one analysis pair: the configured calculator and its outputs.

The only code that runs a VOD calculator. :class:`~canvodpy.vod_computer.VodComputer`
calls it in the main process and the VOD phase
(:mod:`canvodpy.orchestrator.vod_phase`) in its workers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import structlog

from canvodpy.factories import VODFactory

if TYPE_CHECKING:
    import xarray as xr


def compute_vod(
    canopy_ds: xr.Dataset,
    sky_ds: xr.Dataset,
    *,
    analysis_name: str,
    canopy_receiver: str,
    reference_receiver: str,
    calculator: str,
    calculator_params: Mapping[str, Any],
    store_delta_snr: bool,
    store_radial_diff: bool,
) -> xr.Dataset:
    """The VOD of one analysis pair, with the optional outputs.

    The calculator aligns both datasets on their shared epochs and
    signals. ``store_delta_snr`` keeps ``delta_snr`` (dropped otherwise);
    ``store_radial_diff`` adds ``radial_diff`` (canopy minus reference
    slant range, needs ``r`` from ``store_radial_distance`` at ingest).
    Runs in the main process (:class:`~canvodpy.vod_computer.VodComputer`) and in the workers of
    the VOD phase (:mod:`canvodpy.orchestrator.vod_phase`).
    """
    vod_calculator = VODFactory.create(
        calculator, canopy_ds=canopy_ds, sky_ds=sky_ds, **calculator_params
    )
    vod_ds = vod_calculator.calculate_vod()
    if not store_delta_snr:
        vod_ds = vod_ds.drop_vars("delta_snr", errors="ignore")
    if store_radial_diff:
        aligned_canopy, aligned_sky = vod_calculator.canopy_ds, vod_calculator.sky_ds
        if "r" in aligned_canopy and "r" in aligned_sky:
            radial_diff = aligned_canopy["r"] - aligned_sky["r"]
            radial_diff.attrs["units"] = "m"
            radial_diff.attrs["long_name"] = (
                "radial distance difference (canopy − reference)"
            )
            vod_ds["radial_diff"] = radial_diff
        else:
            structlog.get_logger(__name__).warning(
                "radial_diff_unavailable",
                reason=(
                    "store_radial_diff=true but 'r' not present in receiver "
                    "data; set store_radial_distance=true at ingest time"
                ),
            )
    vod_ds.attrs["analysis_name"] = analysis_name
    vod_ds.attrs["canopy_receiver"] = canopy_receiver
    vod_ds.attrs["reference_receiver"] = reference_receiver
    vod_ds.attrs["calculator"] = calculator
    return vod_ds
