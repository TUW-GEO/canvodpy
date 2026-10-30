"""Tests for the §44 network-wide shared aux cache lookup/populate logic.

``RinexDataProcessor`` has no lightweight unit-test harness anywhere in this
repo (requires a real ``GnssResearchSite``/Icechunk store) -- these tests
call ``_ensure_shared_aux_cache`` as an unbound method against a minimal
stand-in ``self`` carrying only the attributes it actually touches, a
standard technique for testing a method in isolation from full object
construction.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from canvodpy.orchestrator.processor import RinexDataProcessor

from canvod.auxiliary.cache_fingerprint import (
    CANONICAL_AUX_GRID_SECONDS,
    compute_aux_cache_fingerprint,
)

FINGERPRINT = compute_aux_cache_fingerprint(
    agency="COD",
    product_type="final",
    ephemeris_source="precise",
    canonical_grid_seconds=CANONICAL_AUX_GRID_SECONDS,
    source_file_paths={},
    aggregate_glonass_fdma=True,
)


def _fake_self(tmp_path: Path) -> SimpleNamespace:
    logger = mock.MagicMock()
    aux_pipeline = mock.MagicMock()
    aux_pipeline.source_file_paths.return_value = {}
    config = mock.MagicMock()
    config.processing.aux_data.agency = "COD"
    config.processing.aux_data.product_type = "final"
    config.processing.params.ephemeris_source = "precise"
    config.processing.params.aggregate_glonass_fdma = True
    fake_self = SimpleNamespace(
        _logger=logger,
        aux_pipeline=aux_pipeline,
        _config=config,
        _preprocess_aux_data_with_hermite=mock.MagicMock(),
    )
    fake_self._shared_aux_cache_entry = lambda *args: (
        RinexDataProcessor._shared_aux_cache_entry(fake_self, *args)
    )
    return fake_self


def test_cache_hit_skips_preprocessing(tmp_path: Path) -> None:
    fake_self = _fake_self(tmp_path)
    shared_cache_dir = tmp_path / "shared"
    cache_root = shared_cache_dir / "aux_cache.zarr"
    (cache_root / FINGERPRINT / "2025213").mkdir(parents=True)

    store_path, group = RinexDataProcessor._ensure_shared_aux_cache(
        fake_self, [], "2025213", shared_cache_dir
    )

    assert store_path == cache_root
    assert group == f"{FINGERPRINT}/2025213"
    fake_self._preprocess_aux_data_with_hermite.assert_not_called()


def test_cache_miss_builds_and_promotes(tmp_path: Path) -> None:
    fake_self = _fake_self(tmp_path)
    shared_cache_dir = tmp_path / "shared"
    cache_root = shared_cache_dir / "aux_cache.zarr"

    def fake_preprocess(
        _files,
        output_path,
        reader_format=None,
        group=None,
        grid_seconds=None,
        per_satellite=False,
    ):
        (output_path / group).mkdir(parents=True)

    fake_self._preprocess_aux_data_with_hermite.side_effect = fake_preprocess

    store_path, group = RinexDataProcessor._ensure_shared_aux_cache(
        fake_self, [], "2025213", shared_cache_dir
    )

    assert store_path == cache_root
    assert group == f"{FINGERPRINT}/2025213"
    assert (cache_root / FINGERPRINT / "2025213").exists()
    # temp group promoted away, not left behind
    tmp_dirs = list((cache_root / FINGERPRINT).glob(".tmp-*"))
    assert tmp_dirs == []
    fake_self._preprocess_aux_data_with_hermite.assert_called_once()
    call_kwargs = fake_self._preprocess_aux_data_with_hermite.call_args.kwargs
    assert call_kwargs["grid_seconds"] == CANONICAL_AUX_GRID_SECONDS
    # Once per satellite: the entry holds all signals, about 16 per satellite
    assert call_kwargs["per_satellite"] is True
    assert call_kwargs["group"].startswith(f"{FINGERPRINT}/.tmp-2025213-")


def test_failed_preprocessing_leaves_no_partial_entry_at_final_path(
    tmp_path: Path,
) -> None:
    fake_self = _fake_self(tmp_path)
    shared_cache_dir = tmp_path / "shared"
    cache_root = shared_cache_dir / "aux_cache.zarr"
    fake_self._preprocess_aux_data_with_hermite.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        RinexDataProcessor._ensure_shared_aux_cache(
            fake_self, [], "2025213", shared_cache_dir
        )

    assert not (cache_root / FINGERPRINT / "2025213").exists()


def test_second_miss_after_a_successful_populate_is_a_hit(tmp_path: Path) -> None:
    fake_self = _fake_self(tmp_path)
    shared_cache_dir = tmp_path / "shared"
    cache_root = shared_cache_dir / "aux_cache.zarr"

    def fake_preprocess(
        _files,
        output_path,
        reader_format=None,
        group=None,
        grid_seconds=None,
        per_satellite=False,
    ):
        (output_path / group).mkdir(parents=True)

    fake_self._preprocess_aux_data_with_hermite.side_effect = fake_preprocess

    RinexDataProcessor._ensure_shared_aux_cache(
        fake_self, [], "2025213", shared_cache_dir
    )
    RinexDataProcessor._ensure_shared_aux_cache(
        fake_self, [], "2025213", shared_cache_dir
    )

    fake_self._preprocess_aux_data_with_hermite.assert_called_once()
    assert (cache_root / FINGERPRINT / "2025213").exists()


@pytest.mark.parametrize(
    ("shared_cache", "expected"),
    [(True, None), (False, ["G01|L1|C"])],
    ids=["shared cache: all signals", "no shared cache: the site's"],
)
def test_the_orbits_for_the_shared_cache_keep_all_signals(
    tmp_path: Path, shared_cache: bool, expected: list[str] | None
) -> None:
    # The entry's fingerprint leaves keep_sids out, so a site keeping more
    # signals reuses it: it must hold every signal, not the first site's
    fake_self = _fake_self(tmp_path)
    fake_self._config.processing.storage.get_shared_aux_cache_dir.return_value = (
        tmp_path / "shared" if shared_cache else None
    )
    fake_self.keep_sids = ["G01|L1|C"]
    fake_self.aux_file_path = tmp_path
    fake_self._agency = "COD"
    fake_self._product_type = "final"
    fake_self._ftp_server = None
    fake_self.matched_data_dirs = mock.MagicMock()
    fake_self.matched_data_dirs.yyyydoy.to_str.return_value = "2025213"

    with mock.patch(
        "canvodpy.orchestrator.processor.AuxDataPipeline.create_standard"
    ) as create_standard:
        RinexDataProcessor._initialize_aux_pipeline(fake_self)

    assert create_standard.call_args.kwargs["keep_sids"] == expected
