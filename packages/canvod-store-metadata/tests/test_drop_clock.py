"""Stores made with CLK files lose their clock variable (#456).

``processing.aux_data.fetch_clock`` is off by default since v1.0.0, and VOD
doesn't use the clock. A GNSS store made with it on holds a ``clock``
variable and records ``fetch_clock: true``; a run with the default would be
refused by both. ``drop_clock`` removes the variable and records
``fetch_clock: false``; ``follow_gnss_content_hash`` gives the site's VOD
store the GNSS store's new content-settings hash.
"""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import zarr
from canvod.utils import testing
from icechunk.xarray import to_icechunk
from test_vod_content_settings import GNSS_NAMES, NAMES
from test_writers import _settings

from canvod.store_metadata import (
    commit_with_rebase,
    ensure_store_metadata,
    open_repository,
    read_repository_metadata,
)
from canvod.store_metadata.content import ContentSettingsError
from canvod.store_metadata.migration import (
    clock_to_drop,
    drop_clock,
    follow_gnss_content_hash,
)


def _settings_with_clock(tmp_path: Path, fetch_clock: bool):
    settings = _settings(tmp_path)
    settings.processing.aux_data.fetch_clock = fetch_clock
    return settings


def _gnss(path: Path, settings) -> dict:
    return ensure_store_metadata(
        path,
        config=settings,
        site_name=testing.SITE_KEY,
        store_type="gnss_store",
        source_format="rinex3",
        names=GNSS_NAMES,
    )


def _vod(path: Path, settings, gnss_repository: dict) -> dict:
    return ensure_store_metadata(
        path,
        config=settings,
        site_name=testing.SITE_KEY,
        store_type="vod_store",
        source_format="tau_omega",
        names=NAMES,
        gnss_repository=gnss_repository,
    )


def _write_group(path: Path, settings, *, clock: bool) -> None:
    """A receiver group of four epochs, with a clock variable if ``clock``."""
    epochs = np.array(
        ["2025-01-01T00:00:00", "2025-01-01T00:00:05"], dtype="datetime64[ns]"
    )
    data = {"SNR": (("epoch", "sid"), np.full((2, 1), 40.0))}
    if clock:
        data["clock"] = (("epoch", "sid"), np.full((2, 1), 1e-4))
    ds = xr.Dataset(data, coords={"epoch": epochs, "sid": ["G01|L1|C"]})
    session = open_repository(path).writable_session("main")
    to_icechunk(ds, session, group="canopy_01")
    commit_with_rebase(session, "data", store_path=path, config=settings)


@pytest.fixture
def clock_settings(tmp_path):
    return _settings_with_clock(tmp_path, True)


@pytest.fixture
def default_settings(tmp_path):
    return _settings_with_clock(tmp_path, False)


@pytest.fixture
def gnss(tmp_path, clock_settings) -> Path:
    path = tmp_path / "gnss"
    _gnss(path, clock_settings)
    _write_group(path, clock_settings, clock=True)
    return path


def _group_arrays(path: Path) -> set[str]:
    session = open_repository(path).readonly_session(branch="main")
    return set(zarr.open_group(session.store, mode="r", path="canopy_01").array_keys())


def test_a_run_without_clock_files_is_refused_before(gnss, default_settings):
    with pytest.raises(ContentSettingsError, match="fetch_clock"):
        _gnss(gnss, default_settings)


def test_the_plan_names_the_groups_with_a_clock(gnss):
    assert clock_to_drop(gnss) == ["canopy_01"]


def test_the_clock_is_dropped_and_fetch_clock_recorded_off(
    gnss, clock_settings, default_settings
):
    drop_clock(gnss, who="NFB", config=clock_settings)

    assert "clock" not in _group_arrays(gnss)
    assert "SNR" in _group_arrays(gnss)
    content = read_repository_metadata(gnss)["content_settings"]
    assert content["settings"]["processing"]["aux_data"]["fetch_clock"] is False
    change = content["changes"][-1]
    assert change["key"] == "processing.aux_data.fetch_clock"
    assert (change["old"], change["new"], change["who"]) == (True, False, "NFB")
    # A run with the default settings now writes.
    _gnss(gnss, default_settings)


def test_the_new_hash_is_the_hash_of_a_new_store_without_clock_files(
    gnss, clock_settings, default_settings, tmp_path
):
    drop_clock(gnss, who="NFB", config=clock_settings)
    fresh = _gnss(tmp_path / "gnss-fresh", default_settings)

    dropped = read_repository_metadata(gnss)["content_settings"]["hash"]
    assert dropped == fresh["content_settings"]["hash"]


def test_a_store_without_a_clock_has_nothing_to_drop(tmp_path, default_settings):
    path = tmp_path / "gnss"
    _gnss(path, default_settings)
    _write_group(path, default_settings, clock=False)

    assert clock_to_drop(path) is None
    assert drop_clock(path, who="NFB", config=default_settings) is None


def test_the_vod_store_follows_the_new_gnss_hash(
    gnss, clock_settings, default_settings, tmp_path
):
    vod = tmp_path / "vod"
    _vod(vod, clock_settings, read_repository_metadata(gnss))
    drop_clock(gnss, who="NFB", config=clock_settings)
    gnss_repository = read_repository_metadata(gnss)
    with pytest.raises(ContentSettingsError, match="gnss_content_hash"):
        _vod(vod, default_settings, gnss_repository)

    follow_gnss_content_hash(vod, gnss, who="NFB", config=default_settings)

    _vod(vod, default_settings, gnss_repository)
    content = read_repository_metadata(vod)["content_settings"]
    assert content["gnss_content_hash"] == gnss_repository["content_settings"]["hash"]


def test_a_vod_store_of_other_gnss_settings_does_not_follow(
    gnss, clock_settings, default_settings, tmp_path
):
    other_settings = default_settings.model_copy(deep=True)
    params = other_settings.processing.params
    params.store_radial_distance = not params.store_radial_distance
    other = tmp_path / "gnss-other"
    _gnss(other, other_settings)
    vod = tmp_path / "vod"
    _vod(vod, other_settings, read_repository_metadata(other))
    drop_clock(gnss, who="NFB", config=clock_settings)

    with pytest.raises(ValueError, match="other content settings"):
        follow_gnss_content_hash(vod, gnss, who="NFB", config=default_settings)
