"""The agency aux store of a day is named per site and sampling interval (#576).

Without a shared aux cache, every run writes the interpolated orbits of
the day to a Zarr store in ``aux_data_dir`` and deletes an existing store
of that name first. Its content depends on the site's sampling interval
(the epoch grid) and signals, so two runs of the same day that differ in
either must not share the store: the second run would delete it while
the first one reads it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.utils.tools.date_utils import YYYYDOY


def _fake_processor(aux_dir: Path, site_name: str) -> SimpleNamespace:
    config = mock.MagicMock()
    config.processing.storage.get_shared_aux_cache_dir.return_value = None
    config.processing.storage.get_aux_data_dir.return_value = aux_dir

    def write_store(rinex_files, output_path, **kwargs):
        output_path.mkdir(parents=True)
        (output_path / "written_by").write_text(site_name)
        return kwargs["sampling_interval"]

    fake = SimpleNamespace(
        _logger=mock.MagicMock(),
        _config=config,
        site=SimpleNamespace(site_name=site_name),
        matched_data_dirs=SimpleNamespace(yyyydoy=YYYYDOY(year=2025, doy=1)),
        _parse_sampling_interval_from_filename=(
            RinexDataProcessor._parse_sampling_interval_from_filename
        ),
        _preprocess_aux_data_with_hermite=write_store,
    )
    fake._detect_sampling_interval = lambda files, reader_format=None: (
        RinexDataProcessor._detect_sampling_interval(fake, files, reader_format)
    )
    return fake


def _ensure(fake: SimpleNamespace, file_name: str) -> Path:
    path, group = RinexDataProcessor._ensure_aux_data_preprocessed(
        fake, [Path(file_name)], "2025001"
    )
    assert group is None
    return path


def test_runs_of_two_sites_on_the_same_day_write_separate_stores(
    tmp_path: Path,
) -> None:
    fangorn = _ensure(
        _fake_processor(tmp_path, "Fangorn"), "FANG01INK_R_20250010000_01D_05S_AA.rnx"
    )
    rohan = _ensure(
        _fake_processor(tmp_path, "Rohan"), "ROHA01INK_R_20250010000_01D_05S_AA.rnx"
    )

    assert fangorn != rohan
    assert (fangorn / "written_by").read_text() == "Fangorn"
    assert (rohan / "written_by").read_text() == "Rohan"


def test_runs_with_two_sampling_intervals_write_separate_stores(
    tmp_path: Path,
) -> None:
    every_5_s = _ensure(
        _fake_processor(tmp_path, "Fangorn"), "FANG01INK_R_20250010000_01D_05S_AA.rnx"
    )
    every_30_s = _ensure(
        _fake_processor(tmp_path, "Fangorn"), "FANG01INK_R_20250010000_01D_30S_AA.rnx"
    )

    assert every_5_s != every_30_s
    assert every_5_s.exists()
    assert every_30_s.exists()


def test_the_store_name_says_day_site_and_sampling_interval(tmp_path: Path) -> None:
    path = _ensure(
        _fake_processor(tmp_path, "Fangorn"), "FANG01INK_R_20250010000_01D_05S_AA.rnx"
    )

    assert path == tmp_path / "00_aux_zarr" / "aux_2025001_Fangorn_5s.zarr"


def test_a_second_run_of_the_same_site_and_sampling_rebuilds_the_store(
    tmp_path: Path,
) -> None:
    first = _ensure(
        _fake_processor(tmp_path, "Fangorn"), "FANG01INK_R_20250010000_01D_05S_AA.rnx"
    )
    second = _ensure(
        _fake_processor(tmp_path, "Fangorn"), "FANG01INK_R_20250010000_01D_05S_AA.rnx"
    )

    assert first == second
    assert (second / "written_by").read_text() == "Fangorn"
