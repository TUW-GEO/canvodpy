"""A broadcast run of RINEX files takes the angles from navigation files.

Half an hour of the Rosalia RINEX test data (both receivers, 2025-001)
through ``canvodpy run`` with ``ephemeris_source: broadcast``: the satellite
positions come from RINEX navigation files, so no orbit products are read
(#567). Each receiver uses its own navigation files; in shared-position
mode the reference uses the canopy's (#572). Locally only: it reads the test data, which CI never
checks out.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from synthetic_days import ROSALIA, TEST_DATA
from typer.testing import CliRunner

from canvod.config import loader as config_loader_module
from canvod.store import MyIcechunkStore
from canvod.utils import testing

NAV = TEST_DATA / "rinex_v3_04_nav_data"
DAY = "2025001"
STARTS = ("0000", "0015")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not NAV.exists(),
        reason="Integration test requires the test data (git submodule)",
    ),
]

#: Receiver, its test-data folders and the identity of its canonical names.
RECEIVERS = {
    "canopy_01": ("02_canopy", "ract", "ROSA01TUW"),
    "reference_01": ("01_reference", "rref", "ROSR01TUW"),
}


def _link_receiver(root: Path, name: str, with_nav: bool) -> None:
    """Two observation files and their navigation files, canonically named.

    The navigation files of the test data have RINEX short names
    (``ract001a00.25p``: hour ``a`` = 00, minute 00).
    """
    folder, short, identity = RECEIVERS[name]
    (root / name).mkdir(parents=True)
    (root / f"{name}_nav").mkdir()
    for start in STARTS:
        obs = f"{identity}_R_{DAY}{start}_15M_05S_AA.rnx"
        (root / name / obs).symlink_to(ROSALIA / folder / "01_GNSS/01_raw/25001" / obs)
        if with_nav:
            hour = chr(ord("a") + int(start[:2]))
            nav = NAV / folder / f"{short}{DAY[4:]}{hour}{start[2:]}.25p"
            canonical = f"{identity}_R_{DAY}{start}_15M_00U_AA.nav"
            (root / f"{name}_nav" / canonical).symlink_to(nav)


def _settings(
    tmp_path: Path,
    monkeypatch,
    nav: tuple[str, ...] = tuple(RECEIVERS),
    position_mode: str = "per_receiver",
    nav_files: bool = True,
) -> Path:
    """Settings of a broadcast run; the receivers in ``nav`` get a
    ``nav_directory``, with their navigation files if ``nav_files``."""
    folder = tmp_path / "settings"
    path = testing.write_settings(folder)
    settings = json.loads(path.read_text())
    settings["processing"]["params"] = {
        "ephemeris_source": "broadcast",
        "receiver_position_mode": position_mode,
    }
    data = tmp_path / "data"
    for name in RECEIVERS:
        _link_receiver(data, name, with_nav=nav_files and name in nav)
    receivers = {
        "reference_01": {
            "type": "reference",
            "directory": "reference_01",
            "reader_format": "rinex3",
            "paired_canopies": "all",
        },
        "canopy_01": {
            "type": "canopy",
            "directory": "canopy_01",
            "reader_format": "rinex3",
        },
    }
    for name in nav:
        receivers[name]["nav_directory"] = f"{name}_nav"
    settings["sites"][testing.SITE_KEY] = {
        "gnss_site_data_root": str(data),
        "store_description": "Half an hour of RINEX observations from the test data.",
        "receivers": receivers,
        "vod_analyses": {
            "canopy_01_vs_reference_01": {
                "canopy_receiver": "canopy_01",
                "reference_receiver": "reference_01",
            }
        },
    }
    path.write_text(json.dumps(settings))
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    config_loader_module._load_config_cached.cache_clear()
    return folder / "stores" / testing.SITE_KEY


@pytest.fixture(autouse=True)
def _fresh_config():
    yield
    config_loader_module._load_config_cached.cache_clear()


def _run():
    from canvodpy.cli.app import main_app

    return CliRunner().invoke(
        main_app, ["run", "--site", testing.SITE_KEY, "--start", DAY, "--end", DAY]
    )


def _assert_angles(stores: Path) -> None:
    """Both receivers' stores hold angles of every system the default
    signals keep."""
    gnss = MyIcechunkStore(stores / "gnss", store_type="gnss_store")
    for group in gnss.list_groups():
        ds = gnss.read_group(group, drop_empty=True)
        for system in "GERC":
            sids = [s for s in ds.sid.values if str(s).startswith(system)]
            assert np.isfinite(ds["theta"].sel(sid=sids).values).any(), (group, system)
            assert np.isfinite(ds["phi"].sel(sid=sids).values).any(), (group, system)


def _nav_stores(stores: Path) -> list[str]:
    """The receivers whose navigation files gave an aux store."""
    prefix = f"aux_{DAY}_{testing.SITE_KEY}_"
    return sorted(
        p.name.removeprefix(prefix).removesuffix("_nav.zarr")
        for p in (stores.parents[1] / "aux" / "00_aux_zarr").glob("*_nav.zarr")
    )


def test_a_broadcast_run_of_rinex_files_writes_angles(tmp_path, monkeypatch):
    stores = _settings(tmp_path, monkeypatch)

    result = _run()

    assert result.exit_code == 0, result.output
    _assert_angles(stores)
    # One aux store per site, receiver and day (runs of other sites with the
    # same receiver names share the aux folder): each receiver uses its own
    # navigation files
    assert _nav_stores(stores) == sorted(RECEIVERS)


def test_shared_position_reference_uses_the_canopy_navigation_files(
    tmp_path, monkeypatch
):
    stores = _settings(
        tmp_path, monkeypatch, nav=("canopy_01",), position_mode="shared"
    )

    result = _run()

    assert result.exit_code == 0, result.output
    _assert_angles(stores)
    assert _nav_stores(stores) == ["canopy_01"]
    # Same position and same navigation files: the same angles wherever both
    # receivers observe a signal
    gnss = MyIcechunkStore(stores / "gnss", store_type="gnss_store")
    canopy = gnss.read_group("canopy_01", drop_empty=True)
    reference = gnss.read_group("reference_01_canopy_01", drop_empty=True)
    canopy, reference = xr.align(canopy, reference, join="inner")
    both = np.isfinite(canopy["theta"]) & np.isfinite(reference["theta"])
    assert both.sum() > 1000
    for angle in ("theta", "phi"):
        np.testing.assert_allclose(
            reference[angle].values[both], canopy[angle].values[both], atol=1e-9
        )


def test_a_day_without_navigation_files_stops_the_run(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, nav_files=False)

    result = _run()

    assert result.exit_code != 0
    message = " ".join(f"{result.output} {result.exception}".split())
    assert "canopy_01" in message or "reference_01" in message
    assert DAY in message
    assert "_nav" in message
