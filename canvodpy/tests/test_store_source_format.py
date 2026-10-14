"""The GNSS store records the format of the reader that read the files.

The worker puts the reader's own ``source_format`` on each dataset
(``"Source Format"``); the store's ``source_format`` root attribute and
its metadata ``identity.source_format`` come from there, never from the
configured reader name and never from a default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from canvodpy.factories import ReaderFactory
from canvodpy.orchestrator.processor import RinexDataProcessor
from test_cross_group_batch_write import _TestProcessor
from test_day_block_write import _file

from canvod.config import load_config
from canvod.config.models import ReceiverConfig
from canvod.store import MyIcechunkStore
from canvod.store_metadata.io import metadata_exists, read_metadata
from canvod.store_metadata.testing import create_test_store
from canvod.utils import testing


class _SourceFormatProcessor(_TestProcessor):
    """The batch-write stand-in, with the real metadata-first step."""

    _ensure_gnss_store_metadata = RinexDataProcessor._ensure_gnss_store_metadata


@pytest.fixture
def new_store(tmp_path: Path) -> MyIcechunkStore:
    """A store without metadata, as before a site's first run."""
    store_path = tmp_path / "store"
    store_path.mkdir()
    return MyIcechunkStore(create_test_store(store_path))


@pytest.fixture
def proc(tmp_path: Path, new_store: MyIcechunkStore) -> _SourceFormatProcessor:
    proc = _SourceFormatProcessor(new_store)
    proc.site.site_name = testing.SITE_KEY
    testing.write_settings(tmp_path / "settings")
    config = load_config(config_dir=tmp_path / "settings").model_copy(deep=True)
    site = config.sites.sites[testing.SITE_KEY]
    site.store_description = "GNSS-T observations below an Ent canopy"
    site.receivers["reference_01"] = ReceiverConfig(
        type="reference", directory="01_reference", paired_canopies=["canopy_01"]
    )
    proc._config = config
    return proc


def _read_by(reader_name: str, file_id: str = "a"):
    """A file read by ``reader_name``'s reader, as the worker returns it."""
    reader = ReaderFactory.component_class(reader_name).model_construct()
    path, ds = _file(file_id, slot=0)
    ds.attrs["Source Format"] = reader.source_format
    return path, ds, reader.source_format


def _write(proc, path_name: str, groups):
    """Write ``groups`` through the batch write or the day-block write.

    The configured format is always ``"rinex3"``: the store must not
    record it.
    """
    inputs = [
        (name, files, [f for f, _ in files], None, None, "rinex3")
        for name, files in groups
    ]
    if path_name == "day_blocks":
        return proc._write_day_blocks(inputs)
    return proc._write_receiver_batch_forked(inputs)


@pytest.mark.parametrize("path_name", ["forked", "day_blocks"])
@pytest.mark.parametrize("reader_name", ["rinex3", "rinex3_stripped", "sbf"])
def test_the_store_records_the_format_of_the_reader(
    proc, new_store, reader_name, path_name
) -> None:
    path, ds, source_format = _read_by(reader_name)

    _write(proc, path_name, [("canopy_01", [(path, ds)])])

    assert new_store.source_format == source_format
    identity = read_metadata(new_store.store_path).identity
    assert identity.source_format == source_format


def test_without_a_format_the_metadata_step_raises(proc, new_store) -> None:
    with pytest.raises(ValueError, match="canopy_01"):
        proc._ensure_gnss_store_metadata(["canopy_01"], None)

    assert not metadata_exists(new_store.store_path)


@pytest.mark.parametrize("path_name", ["forked", "day_blocks"])
def test_files_without_a_format_are_not_written(proc, new_store, path_name) -> None:
    path, ds, _ = _read_by("sbf")
    del ds.attrs["Source Format"]

    with pytest.raises(ValueError, match="canopy_01"):
        _write(proc, path_name, [("canopy_01", [(path, ds)])])

    assert new_store.source_format is None
    assert not new_store.list_groups()


def test_two_formats_in_one_store_are_refused(proc, new_store) -> None:
    sbf_path, sbf_ds, _ = _read_by("sbf", "a")
    rnx_path, rnx_ds, _ = _read_by("rinex3", "b")

    with pytest.raises(ValueError, match="sbf"):
        _write(
            proc,
            "forked",
            [
                ("canopy_01", [(sbf_path, sbf_ds)]),
                ("reference_01_canopy_01", [(rnx_path, rnx_ds)]),
            ],
        )

    assert not new_store.list_groups()
