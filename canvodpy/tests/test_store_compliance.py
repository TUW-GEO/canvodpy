"""The stores meet CF 1.11 and ACDD 1.3 (#208), checked by IOOS compliance-checker.

A day of the test data is exported to netCDF with the root attributes, and
compliance-checker runs on it offline. Pass rule: no failed check of high
priority (CF mandatory, ACDD highly recommended) apart from the known
exceptions in ``_known``.
"""

import json
import re
from pathlib import Path
from typing import Any

import icechunk
import pytest
import xarray as xr
import zarr

from canvod.store_metadata import read_metadata, validate_all
from canvod.vod import TauOmegaZerothOrder

pytest.importorskip("compliance_checker")


def _known(spec: str, check: str, msg: str) -> bool:
    """A finding that is not a failure of the stores."""
    if spec.startswith("acdd"):
        # CF has no standard names for these quantities (#208, part 1).
        if msg == "standard_name":
            return True
        # A grid cell id is an index, not a quantity: it has no units.
        if msg == "units" and check.startswith('variable "cell_id_'):
            return True
    # UDUNITS has no logarithmic units; the SNR unit comes from the file.
    return bool(
        spec.startswith("cf")
        and re.fullmatch(
            r'units for (SNR|CN0|delta_snr), "(dB|dB-Hz)" are not recognized by '
            r"UDUNITS",
            msg,
        )
    )


def _netcdf_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Root attributes as netCDF global attributes.

    netCDF attributes are flat: the zarr conventions (nested objects) and
    the ``canvod:`` attributes stay in the store, and the license is its
    SPDX id.
    """
    flat = {
        name: value
        for name, value in attrs.items()
        if ":" not in name and isinstance(value, str | int | float)
    }
    if isinstance(attrs.get("license"), dict):
        flat["license"] = attrs["license"].get("spdx") or attrs["license"]["url"]
    return flat


def _failures(ds: xr.Dataset, root_attrs: dict[str, Any], path: Path) -> list[str]:
    from compliance_checker.runner import CheckSuite, ComplianceChecker

    ds.assign_attrs(_netcdf_attrs(root_attrs)).to_netcdf(path / "day.nc")
    CheckSuite.load_all_available_checkers()
    report_path = path / "report.json"
    ComplianceChecker.run_checker(
        str(path / "day.nc"),
        ["cf:1.11", "acdd:1.3"],
        verbose=2,
        criteria="normal",
        output_filename=str(report_path),
        output_format="json",
    )
    report = json.loads(report_path.read_text())
    failures = []
    for spec, result in report.items():
        assert not result.get("errors"), f"{spec} checker errors: {result['errors']}"
        for check in result["high_priorities"]:
            score, out_of = check["value"]
            if score < out_of:
                failures += [
                    f"{spec}: {check['name']} {msg}"
                    for msg in check["msgs"]
                    if not _known(spec, check["name"], msg)
                ]
    return failures


def _store(config) -> tuple[Path, Any]:
    store_path = config.processing.storage.get_gnss_store_path("fangorn")
    session = icechunk.Repository.open(
        storage=icechunk.local_filesystem_storage(str(store_path))
    ).readonly_session(branch="main")
    return store_path, session


@pytest.mark.integration
def test_a_new_store_has_no_validation_failures(rosalia_one_day):
    config, _ = rosalia_one_day
    store_path, _ = _store(config)

    result = validate_all(read_metadata(store_path), recommended=False)

    assert result == {
        "zarr_conventions": [],
        "acdd": [],
        "datacite": [],
        "stac": [],
        "fair": [],
    }


@pytest.mark.integration
def test_a_gnss_store_day_meets_cf_and_acdd(rosalia_one_day, tmp_path):
    config, _ = rosalia_one_day
    _, session = _store(config)
    attrs = dict(zarr.open_group(session.store, mode="r").attrs)
    ds = xr.open_zarr(session.store, group="canopy_01", consolidated=False)

    assert _failures(ds.load(), attrs, tmp_path) == []


@pytest.mark.integration
def test_a_vod_day_meets_cf_and_acdd(rosalia_one_day, tmp_path):
    config, _ = rosalia_one_day
    _, session = _store(config)
    attrs = dict(zarr.open_group(session.store, mode="r").attrs)
    canopy, sky = (
        xr.open_zarr(session.store, group=group, consolidated=False).load()
        for group in ("canopy_01", "reference_01_canopy_01")
    )

    vod = TauOmegaZerothOrder(canopy_ds=canopy, sky_ds=sky).calculate_vod()

    assert _failures(vod, attrs, tmp_path) == []
