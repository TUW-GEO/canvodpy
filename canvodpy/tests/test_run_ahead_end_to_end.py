"""A run reads the next day while the previous one is handed on (#277).

While the caller works on a day it got from a run (``canvodpy run``
computes and writes its VOD), the run already reads and writes the next
batch, and prepares the batch after it (orbits, clocks, receiver
positions) while the files of a batch are read. One batch at a time, so
two batches' data are in memory at most.

On the Rosalia test data with a synthetic second day (``synthetic_days``),
one day per batch.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import xarray as xr
from synthetic_days import RECEIVERS, site_data

from canvod.store import MyIcechunkStore
from canvod.utils import testing

pytestmark = pytest.mark.integration

DAYS = ("2025001", "2025002")
# The store groups: the canopy, and the reference as paired with it.
GROUPS = ("canopy_01", "reference_01_canopy_01")


def _two_days(root: Path) -> Path:
    """A site folder with both days of both receivers."""
    every_file = dict.fromkeys(RECEIVERS, slice(None))
    return site_data(root / "data", dict.fromkeys(DAYS, every_file), root / "synthetic")


def _use(config, data: Path, stores: Path) -> Path:
    """Point the site at ``data`` and its stores at ``stores``."""
    config.processing.storage.stores_root_dir = stores
    config.sites.sites[testing.SITE_KEY].gnss_site_data_root = str(data)
    return config.processing.storage.get_gnss_store_path(testing.SITE_KEY)


@pytest.fixture
def two_days(rosalia_site, tmp_path):
    config, test_site = rosalia_site
    site = config.sites.sites[testing.SITE_KEY]
    site.receivers = dict(test_site._site_config.receivers)
    return config, _two_days(tmp_path)


def _pipeline():
    from canvodpy import Site

    # rescan: the file index of an earlier run would hide files added to a
    # folder of old days (#299)
    return Site(testing.SITE_KEY).pipeline(n_workers=2, days_per_batch=1, rescan=True)


def _stored(store_path: Path) -> dict[str, set[str]]:
    """The days (YYYY-MM-DD) each group's log book has stored files of."""
    if not store_path.exists():
        return {}
    store = MyIcechunkStore(store_path)
    days: dict[str, set[str]] = {}
    for group in store.list_groups() or []:
        with store.readonly_session("main") as session:
            rows = store.read_metadata_table(session, group)
        stored = rows.filter(rows["action"].is_in(["initial", "written"]))
        days[group] = {str(start)[:10] for start in stored["start"].to_list()}
    return days


def _assert_whole_days(store_path: Path) -> None:
    """Every stored file's epochs are in the group, and no others."""
    store = MyIcechunkStore(store_path)
    for group in store.list_groups() or []:
        with store.readonly_session("main") as session:
            rows = store.read_metadata_table(session, group)
        stored = rows.filter(rows["action"].is_in(["initial", "written"]))
        data = store.read_group(group, drop_empty=True)
        assert data.sizes["epoch"] == int(stored["epochs"].sum()), group


def _no_run_threads_left() -> bool:
    return not [t for t in threading.enumerate() if t.name.startswith("canvodpy-")]


def test_the_next_day_is_written_while_the_caller_works_on_the_day(two_days, tmp_path):
    config, data = two_days
    store_path = _use(config, data, tmp_path / "stores")
    days = []
    with _pipeline() as pipeline:
        for date_key, datasets in pipeline.process_range(*DAYS):
            days.append(date_key)
            assert set(datasets) == set(GROUPS)
            if date_key != DAYS[0]:
                continue
            # The caller is busy with the first day (VOD, in a run): the run
            # writes the second day meanwhile.
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                stored = _stored(store_path)
                if all("2025-01-02" in stored.get(g, set()) for g in GROUPS):
                    break
                time.sleep(2)
            else:
                pytest.fail("The second day was not written while the first was out.")
    assert days == list(DAYS)
    assert pipeline.failed_receiver_days == ()
    assert _no_run_threads_left()


def test_running_ahead_stores_what_one_day_at_a_time_stores(two_days, tmp_path):
    config, data = two_days
    ahead = _use(config, data, tmp_path / "ahead")
    with _pipeline() as pipeline:
        assert [day for day, _ in pipeline.process_range(*DAYS)] == list(DAYS)

    one_by_one = _use(config, data, tmp_path / "one_by_one")
    for day in DAYS:
        with _pipeline() as pipeline:
            assert [d for d, _ in pipeline.process_range(day, day)] == [day]

    a, b = MyIcechunkStore(ahead), MyIcechunkStore(one_by_one)
    assert sorted(a.list_groups()) == sorted(b.list_groups()) == sorted(GROUPS)
    for group in GROUPS:
        xr.testing.assert_equal(
            a.read_group(group, drop_empty=True).drop_attrs(),
            b.read_group(group, drop_empty=True).drop_attrs(),
        )
        with a.readonly_session("main") as sa, b.readonly_session("main") as sb:
            rows_a = a.read_metadata_table(sa, group)
            rows_b = b.read_metadata_table(sb, group)
        assert set(rows_a["rinex_hash"]) == set(rows_b["rinex_hash"])


def test_an_error_in_the_caller_stops_the_run_and_keeps_written_days(
    two_days, tmp_path
):
    config, data = two_days
    store_path = _use(config, data, tmp_path / "stores")
    with pytest.raises(RuntimeError, match="VOD failed"), _pipeline() as pipeline:
        for _date_key, _datasets in pipeline.process_range(*DAYS):
            raise RuntimeError("VOD failed")

    # The run has stopped, and what it wrote is whole days.
    assert _no_run_threads_left()
    stored = _stored(store_path)
    assert all("2025-01-01" in stored[g] for g in GROUPS)
    _assert_whole_days(store_path)


def test_a_day_that_cannot_be_prepared_fails_loudly_and_keeps_the_day_before(
    two_days, tmp_path
):
    config, data = two_days
    # The second day's files have no approximate position: preparing that
    # day (receiver positions) fails while the first day is read.
    for receiver_dir in RECEIVERS.values():
        for f in (data / receiver_dir / "25002").iterdir():
            lines = f.read_text().splitlines(keepends=True)
            f.unlink()
            f.write_text(
                "".join(line for line in lines if "APPROX POSITION XYZ" not in line)
            )
    store_path = _use(config, data, tmp_path / "stores")
    with _pipeline() as pipeline:
        days = [day for day, _ in pipeline.process_range(*DAYS)]

    assert days == [DAYS[0]]
    assert sorted(pipeline.failed_receiver_days) == sorted(
        (group, DAYS[1]) for group in GROUPS
    )
    assert all(_stored(store_path)[g] == {"2025-01-01"} for g in GROUPS)
    _assert_whole_days(store_path)
