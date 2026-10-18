"""A forked day on the test data stores what one session stores (#275).

A new store's first day is written in one session; a day that already has
its block is written by forks. The same files give the same data either
way, and the forked day is one commit.
"""

from __future__ import annotations

from pathlib import Path

import icechunk
import pytest
import xarray as xr
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.store import MyIcechunkStore
from canvod.utils import testing

DAY = "2025001"
_RAW = "01_GNSS/01_raw/25001"
_RECEIVER_DIRS = ("01_reference", "02_canopy")


def _link_data(data: Path, root: Path, *, half: bool) -> None:
    """Link the test data ``data`` into ``root``: the day's files, or the first half."""
    for aux in ("01_SP3", "02_CLK"):
        if not (root / aux).exists():
            root.mkdir(parents=True, exist_ok=True)
            (root / aux).symlink_to(data / aux)
    for receiver in _RECEIVER_DIRS:
        source = data / receiver / _RAW
        target = root / receiver / _RAW
        target.mkdir(parents=True, exist_ok=True)
        files = sorted(f for f in source.iterdir() if not f.name.startswith("."))
        for f in files[: len(files) // 2] if half else files:
            if not (target / f.name).exists():
                (target / f.name).symlink_to(f)


def _commits(store_path: Path) -> int:
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store_path)))
    return len(list(repo.ancestry(branch="main")))


@pytest.mark.integration
def test_a_forked_day_stores_what_one_session_stores(
    rosalia_site, tmp_path, monkeypatch
) -> None:
    from canvodpy import Site

    config, test_site = rosalia_site
    data = Path(test_site._site_config.gnss_site_data_root)
    site = config.sites.sites[testing.SITE_KEY]
    site.receivers = dict(test_site._site_config.receivers)
    forked: list[str] = []
    commit = RinexDataProcessor._commit_forked_unit

    def counting(self, days):
        forked.extend(day.date_key for _, day, _ in days)
        return commit(self, days)

    monkeypatch.setattr(RinexDataProcessor, "_commit_forked_unit", counting)

    def run(stores: Path, data: Path, n_workers: int) -> Path:
        config.processing.storage.stores_root_dir = stores
        site.gnss_site_data_root = str(data)
        with Site(testing.SITE_KEY).pipeline(n_workers=n_workers) as pipeline:
            pipeline.process_date(DAY)
        return config.processing.storage.get_gnss_store_path(testing.SITE_KEY)

    # One session: a new store's first day.
    _link_data(data, tmp_path / "data_all", half=False)
    one_session = run(tmp_path / "one_session", tmp_path / "data_all", 1)
    assert forked == []

    # Forks: the store holds the day's first half; two workers write the rest.
    _link_data(data, tmp_path / "data_forked", half=True)
    forked_store = run(tmp_path / "forked", tmp_path / "data_forked", 1)
    _link_data(data, tmp_path / "data_forked", half=False)
    before = _commits(forked_store)
    run(tmp_path / "forked", tmp_path / "data_forked", 2)

    assert forked == [DAY]
    assert _commits(forked_store) == before + 1
    a, b = MyIcechunkStore(one_session), MyIcechunkStore(forked_store)
    assert sorted(a.list_groups()) == sorted(b.list_groups())
    for group in a.list_groups():
        expected = a.read_group(group, drop_empty=True)
        stored = b.read_group(group, drop_empty=True)
        assert stored.sizes["epoch"] == expected.sizes["epoch"] > 0
        for name in expected.data_vars:
            xr.testing.assert_equal(
                stored[name].reset_coords(drop=True).drop_attrs(),
                expected[name].reset_coords(drop=True).drop_attrs(),
            )
