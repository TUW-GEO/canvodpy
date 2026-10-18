"""The VOD phase: days in the worker pool, one commit per unit (#426, ADR 0021).

The phase stores the VOD that the current path stores (whole groups read,
one write per day), for several days and two pairs; a second run adds
nothing; a day without data in a group of its pair is skipped and
reported.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from canvodpy.orchestrator.vod_phase import VodPair, VodPhase, units
from canvodpy.vod_computer import compute_vod
from loky import get_reusable_executor

from canvod.config.models import (
    PREPROCESSING_ATTR,
    preprocessing_record,
    vod_preprocessing_record,
)
from canvod.readers.base import SignalID
from canvod.readers.builder import sid_coords
from canvod.readers.gnss_specs.signals import SignalIDMapper
from canvod.store import open_gnss_store, open_vod_store
from canvod.store.day_blocks import add_day_block, load_group, write_file_region
from canvod.store.store import MyIcechunkStore, VodWriteItem
from canvod.store_metadata.testing import give_test_metadata

CALCULATOR = "tau_omega"
CADENCE_S = 30.0
DAYS = [np.datetime64("2025-01-01", "D") + np.timedelta64(i, "D") for i in range(3)]
PAIRS = [
    VodPair("a", "canopy_01", "reference_01", "canopy_01", "reference_01_canopy_01"),
    VodPair("b", "canopy_02", "reference_01", "canopy_02", "reference_01_canopy_02"),
]
RECORD = preprocessing_record([], {"canvod-ops": "1.0.0"})
SIDS = ["G01|L1|C", "G02|L1|C", "G03|L2|W", "E05|L1|C"]


def _receiver_day(day: np.datetime64, seed: int, snr: float) -> xr.Dataset:
    """Two hours of 30 s data of one receiver on ``day``."""
    rng = np.random.default_rng(seed)
    epochs = day.astype("M8[ns]") + np.arange(240) * np.timedelta64(30, "s")
    shape = (epochs.size, len(SIDS))
    return xr.Dataset(
        {
            "SNR": (["epoch", "sid"], snr + rng.normal(0, 2, shape)),
            "theta": (["epoch", "sid"], rng.uniform(0.1, 1.4, shape)),
            "phi": (["epoch", "sid"], rng.uniform(0, 6.2, shape)),
        },
        coords={
            "epoch": ("epoch", epochs, {"time_system": "GPS"}),
            **sid_coords(
                [SignalID.from_string(sid) for sid in SIDS], mapper=SignalIDMapper()
            ),
        },
    )


def _gnss_store(path: Path, skip: set[tuple[str, np.datetime64]]) -> MyIcechunkStore:
    """A GNSS store of both pairs' groups on ``DAYS``, without the ``skip`` days."""
    store = open_gnss_store(give_test_metadata(path, "gnss_store"))
    session = store.repo.writable_session("main")
    groups = {p.canopy_group: 35.0 for p in PAIRS} | {
        p.reference_group: 45.0 for p in PAIRS
    }
    for i, day in enumerate(DAYS):
        for j, (group, snr) in enumerate(groups.items()):
            if (group, day) in skip:
                continue
            ds = _receiver_day(day, seed=10 * i + j, snr=snr)
            add_day_block(session, group, day, CADENCE_S, template=ds)
            write_file_region(session, group, ds)
    session.commit("GNSS test days")
    return store


def _patch_log_book(monkeypatch, store: MyIcechunkStore, tag: str = "") -> None:
    """The GNSS log book: one file per group and day, not preprocessed."""

    def hashes(group, start, end):
        return [f"{group}-{np.datetime64(start, 'D')}{tag}"]

    monkeypatch.setattr(store, "source_file_hashes", hashes)
    monkeypatch.setattr(store, "preprocessing_records", lambda g, s, e: [RECORD])


def _phase(gnss: MyIcechunkStore, vod: MyIcechunkStore, pool) -> VodPhase:
    return VodPhase(
        gnss_store=gnss,
        vod_store=vod,
        pairs=PAIRS,
        calculator=CALCULATOR,
        calculator_params={},
        store_delta_snr=False,
        store_radial_diff=False,
        submit=pool.submit,
    )


def _current_path(gnss: MyIcechunkStore, vod_store: MyIcechunkStore) -> None:
    """What ``canvodpy vod`` stores today: whole groups read, a write per day."""
    with gnss.readonly_session() as session:
        inputs = {
            p.analysis: xr.align(
                load_group(session.store, p.canopy_group).load(),
                load_group(session.store, p.reference_group).load(),
                join="inner",
            )
            for p in PAIRS
        }
    record = vod_preprocessing_record({"canopy": [RECORD], "reference": [RECORD]})
    for day in DAYS:
        items = []
        for pair in PAIRS:
            canopy, sky = inputs[pair.analysis]
            vod = compute_vod(
                canopy,
                sky,
                analysis_name=pair.analysis,
                canopy_receiver=pair.canopy_receiver,
                reference_receiver=pair.reference_receiver,
                calculator=CALCULATOR,
                calculator_params={},
                store_delta_snr=False,
                store_radial_diff=False,
            )
            in_day = vod.epoch.values.astype("M8[D]") == day
            items.append(
                VodWriteItem(
                    group_name=f"{CALCULATOR}/{pair.analysis}",
                    dataset=vod.isel(epoch=np.flatnonzero(in_day)).assign_attrs(
                        {PREPROCESSING_ATTR: record}
                    ),
                    source_file_hashes={"x": str(day)},
                    source_gnss_stores={"x": "gnss"},
                    calculator_name=CALCULATOR,
                    calculator_params={},
                    cadences={day: CADENCE_S},
                )
            )
        vod_store.write_or_append_vod_groups_batch(items)


def _commits(store: MyIcechunkStore) -> int:
    return len(list(store.repo.ancestry(branch="main")))


def _vod(store: MyIcechunkStore, analysis: str) -> xr.Dataset:
    return store.read_group(f"{CALCULATOR}/{analysis}", drop_empty=True).compute()


@pytest.fixture(scope="module")
def pool():
    return get_reusable_executor(max_workers=2)


def test_the_phase_stores_what_the_current_path_stores(
    tmp_path, monkeypatch, pool
) -> None:
    gnss = _gnss_store(tmp_path / "gnss", skip=set())
    _patch_log_book(monkeypatch, gnss)
    phase_store = open_vod_store(give_test_metadata(tmp_path / "vod", "vod_store"))
    current = open_vod_store(give_test_metadata(tmp_path / "current", "vod_store"))

    phase = _phase(gnss, phase_store, pool)
    # The first day creates the groups (the commit writes it); the next two
    # are written by forks of one session.
    first = phase.run_unit(DAYS[:1])
    before = _commits(phase_store)
    rest = phase.run_unit(DAYS[1:])
    _current_path(gnss, current)

    assert first.written == {"a": DAYS[:1], "b": DAYS[:1]}
    assert rest.written == {"a": DAYS[1:], "b": DAYS[1:]}
    # The blocks of the unit's days, then the unit's data: two commits.
    assert _commits(phase_store) == before + 2
    for pair in PAIRS:
        got, want = _vod(phase_store, pair.analysis), _vod(current, pair.analysis)
        assert got.sizes["epoch"] == 3 * 240
        np.testing.assert_array_equal(got.epoch.values, want.epoch.values)
        xr.testing.assert_allclose(got["VOD"], want["VOD"])
    rows = phase_store.log_books.rows(
        phase_store.repo.readonly_session("main"), f"{CALCULATOR}/a"
    )
    assert rows is not None
    assert rows.height == 3
    assert rows["epochs"].to_list() == [240, 240, 240]


def test_running_twice_adds_nothing(tmp_path, monkeypatch, pool) -> None:
    gnss = _gnss_store(tmp_path / "gnss", skip=set())
    _patch_log_book(monkeypatch, gnss)
    store = open_vod_store(give_test_metadata(tmp_path / "vod", "vod_store"))
    phase = _phase(gnss, store, pool)
    for unit in units(DAYS, 2):
        phase.run_unit(unit)
    commits = _commits(store)

    again = phase.run_unit(DAYS)

    assert _commits(store) == commits
    assert again.written == {}
    assert again.stored == {"a": DAYS, "b": DAYS}


def test_a_day_from_other_files_replaces_the_stored_day(
    tmp_path, monkeypatch, pool
) -> None:
    gnss = _gnss_store(tmp_path / "gnss", skip=set())
    _patch_log_book(monkeypatch, gnss)
    store = open_vod_store(give_test_metadata(tmp_path / "vod", "vod_store"))
    _phase(gnss, store, pool).run_unit(DAYS)
    before = _vod(store, "a")

    _patch_log_book(monkeypatch, gnss, tag="-new")
    again = _phase(gnss, store, pool).run_unit(DAYS[1:2])

    assert again.written == {"a": DAYS[1:2], "b": DAYS[1:2]}
    xr.testing.assert_allclose(_vod(store, "a")["VOD"], before["VOD"])
    rows = store.log_books.rows(store.repo.readonly_session("main"), f"{CALCULATOR}/a")
    assert rows is not None
    assert rows["action"].to_list()[-1] == "overwrite"


def test_a_day_without_data_is_skipped_and_reported(
    tmp_path, monkeypatch, pool
) -> None:
    gnss = _gnss_store(tmp_path / "gnss", skip={("canopy_02", DAYS[1])})
    _patch_log_book(monkeypatch, gnss)
    store = open_vod_store(give_test_metadata(tmp_path / "vod", "vod_store"))

    report = _phase(gnss, store, pool).run_unit(DAYS)

    assert report.written == {"a": DAYS, "b": [DAYS[0], DAYS[2]]}
    assert report.missing == {"b": [(DAYS[1], "no data in canopy_02")]}
    assert _vod(store, "b").sizes["epoch"] == 2 * 240
