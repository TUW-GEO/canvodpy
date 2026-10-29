"""A run names the satellites it observed without a position (#571).

A satellite without an orbit record (or product) for an epoch has NaN
angles there, never extrapolated ones. The run says which satellites and
for how many epochs: one line per receiver-day, a warning in the run
history, and per file in the log book. The run seam is a broadcast run of
half an hour of the Rosalia RINEX test data whose navigation files lack
G08; locally only, as CI never checks out the test data.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import zarr
from canvodpy.cli.run import _print_satellites_without_position
from canvodpy.orchestrator.pipeline import _sum_no_position
from canvodpy.orchestrator.processor import satellites_without_position
from canvodpy.run_history import RunHistory
from test_broadcast_rinex_run import DAY, NAV, RECEIVERS, _run, _settings

from canvod.config import loader as config_loader_module
from canvod.store import MyIcechunkStore
from canvod.store.prepare import (
    NO_POSITION_ATTR,
    NO_POSITION_COLUMN,
    split_no_position,
)
from canvod.store.store import _json_log_row
from canvod.store_metadata.log_book import read_log_book

MISSING = "G08"


def _observations(snr: list[list[float]], svs: list[str]) -> xr.Dataset:
    sids = [f"{sv}|L1|C" for sv in svs]
    return xr.Dataset(
        {"SNR": (("epoch", "sid"), np.array(snr))},
        coords={
            "epoch": np.arange(len(snr)),
            "sid": sids,
            "sv": ("sid", svs),
        },
    )


def test_epochs_with_observations_and_nan_angles_are_counted():
    obs = _observations(
        [[40.0, 41.0, np.nan], [40.0, np.nan, 30.0], [40.0, 41.0, 30.0]],
        ["G01", "G02", "G03"],
    )
    theta = xr.DataArray(
        [[0.1, np.nan, np.nan], [0.1, np.nan, np.nan], [0.1, 0.2, 0.3]],
        dims=("epoch", "sid"),
        coords={"sid": obs.sid},
    )

    # G02 at epoch 0 (epoch 1 has no observation); G03 at epoch 1.
    assert satellites_without_position(obs, theta) == {"G02": 1, "G03": 1}


def test_signals_without_ephemeris_count_at_each_observed_epoch():
    obs = _observations([[40.0, 41.0], [40.0, np.nan]], ["G01", "E05"])
    theta = xr.DataArray(
        [[0.1], [0.1]], dims=("epoch", "sid"), coords={"sid": obs.sid[:1]}
    )

    assert satellites_without_position(obs, theta) == {"E05": 1}


def test_a_satellite_counts_an_epoch_once_over_its_signals():
    obs = _observations([[40.0, 41.0], [40.0, 41.0]], ["G01", "G01"])
    obs = obs.assign_coords(sid=["G01|L1|C", "G01|L2|W"])
    theta = xr.DataArray(np.full((2, 2), np.nan), dims=("epoch", "sid"))
    theta = theta.assign_coords(sid=obs.sid)

    assert satellites_without_position(obs, theta) == {"G01": 2}


def test_the_files_of_a_day_are_summed():
    files = [
        {NO_POSITION_ATTR: json.dumps({"G08": 3})},
        {NO_POSITION_ATTR: json.dumps({"G08": 2, "R19": 1})},
        {},
    ]

    assert _sum_no_position(files) == {"G08": 5, "R19": 1}


def test_the_line_names_satellites_and_epochs():
    lines: list[str] = []

    _print_satellites_without_position(
        lines.append, "canopy_01", DAY, {"G08": 360, "R19": 12}
    )

    assert lines == [
        "  no position: canopy_01 on 2025001: G08 (360 epochs), R19 (12 epochs)"
    ]


def test_the_log_book_row_takes_the_list_out_of_the_attributes():
    attrs = {"File Hash": "abc", NO_POSITION_ATTR: '{"G08": 3}'}

    row = _json_log_row({"dataset_attrs": attrs})

    assert row[NO_POSITION_COLUMN] == '{"G08": 3}'
    assert json.loads(row["attrs"]) == {"File Hash": "abc"}
    assert split_no_position(attrs) == ({"File Hash": "abc"}, '{"G08": 3}')


def _without(nav: Path, satellite: str, out: Path) -> None:
    """Copy navigation file ``nav`` to ``out`` without ``satellite``'s records."""
    lines = nav.read_text().splitlines(keepends=True)
    header = next(i for i, line in enumerate(lines) if "END OF HEADER" in line) + 1
    kept = lines[:header]
    dropping = False
    for line in lines[header:]:
        if not line.startswith(" "):
            dropping = line.startswith(satellite)
        if not dropping:
            kept.append(line)
    out.write_text("".join(kept))


@pytest.mark.integration
@pytest.mark.skipif(
    not NAV.exists(),
    reason="Integration test requires the test data (git submodule)",
)
def test_a_run_names_the_satellites_it_observed_without_a_position(
    tmp_path, monkeypatch
):
    stores = _settings(tmp_path, monkeypatch, with_nav=True)
    for name in RECEIVERS:
        for link in (tmp_path / "data" / f"{name}_nav").iterdir():
            target = link.resolve()
            link.unlink()
            _without(target, MISSING, link)

    result = _run()
    config_loader_module._load_config_cached.cache_clear()

    assert result.exit_code == 0, result.output
    gnss = MyIcechunkStore(stores / "gnss", store_type="gnss_store")
    canopy = gnss.read_group("canopy_01", drop_empty=True)
    g08 = canopy.sel(sid=canopy.sv == MISSING)
    observed = np.isfinite(g08["SNR"].values).any(axis=1)
    epochs = int(observed.sum())
    assert epochs > 0
    # Angles are NaN, never extrapolated.
    assert np.isnan(g08["theta"].values).all()

    output = " ".join(result.output.split())
    assert f"no position: canopy_01 on {DAY}:" in output
    assert f"{MISSING} ({epochs} epochs)" in output

    with gnss.readonly_session() as session:
        rows = read_log_book(session.store, "canopy_01")
        attrs = zarr.open_group(session.store, mode="r", path="canopy_01").attrs
    per_file = [json.loads(v) for v in rows[NO_POSITION_COLUMN].to_list()]
    assert sum(f.get(MISSING, 0) for f in per_file) == epochs
    assert NO_POSITION_ATTR not in attrs
    assert all(NO_POSITION_ATTR not in json.loads(a) for a in rows["attrs"])

    with RunHistory.open(stores.parents[1] / "logs", read_only=True) as history:
        (run,) = history.runs()
        messages = [p.message for p in history.problems(run.run_id)]
    assert any(
        m.startswith(f"canopy_01 has satellites without a position on {DAY}:")
        and f"{MISSING} ({epochs} epochs)" in m
        for m in messages
    ), messages
