"""Tests for the network-wide aux cache fingerprint."""

from __future__ import annotations

from pathlib import Path

from canvod.auxiliary.cache_fingerprint import (
    CANONICAL_AUX_GRID_SECONDS,
    compute_aux_cache_fingerprint,
    compute_broadcast_cache_fingerprint,
)


def _fp(**overrides) -> str:
    defaults = {
        "agency": "COD",
        "product_type": "final",
        "ephemeris_source": "precise",
        "canonical_grid_seconds": CANONICAL_AUX_GRID_SECONDS,
        "source_file_paths": {"ephemerides": None, "clock": None},
        "aggregate_glonass_fdma": True,
    }
    defaults.update(overrides)
    return compute_aux_cache_fingerprint(**defaults)


def test_deterministic_for_identical_inputs() -> None:
    assert _fp() == _fp()


def test_sensitive_to_agency() -> None:
    assert _fp(agency="COD") != _fp(agency="GFZ")


def test_sensitive_to_product_type() -> None:
    assert _fp(product_type="final") != _fp(product_type="rapid")


def test_sensitive_to_ephemeris_source() -> None:
    assert _fp(ephemeris_source="precise") != _fp(ephemeris_source="broadcast")


def test_sensitive_to_canonical_grid_seconds() -> None:
    assert _fp(canonical_grid_seconds=1.0) != _fp(canonical_grid_seconds=0.5)


def test_sensitive_to_aggregate_glonass_fdma() -> None:
    assert _fp(aggregate_glonass_fdma=True) != _fp(aggregate_glonass_fdma=False)


def test_source_file_key_order_does_not_matter() -> None:
    a = _fp(source_file_paths={"ephemerides": None, "clock": None})
    b = _fp(source_file_paths={"clock": None, "ephemerides": None})
    assert a == b


def test_sensitive_to_source_file_mtime(tmp_path: Path) -> None:
    sp3 = tmp_path / "COD0.SP3"
    sp3.write_text("dummy")

    fp_before = _fp(source_file_paths={"ephemerides": sp3})

    import os
    import time

    time.sleep(0.01)
    os.utime(sp3, None)  # bump mtime without changing content

    fp_after = _fp(source_file_paths={"ephemerides": sp3})
    assert fp_before != fp_after


def test_missing_source_file_treated_as_none(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.SP3"
    a = _fp(source_file_paths={"ephemerides": missing})
    b = _fp(source_file_paths={"ephemerides": None})
    assert a == b


def test_sensitive_to_format_version(monkeypatch) -> None:
    from canvod.auxiliary import cache_fingerprint

    before = _fp()
    monkeypatch.setattr(
        cache_fingerprint,
        "AUX_CACHE_FORMAT_VERSION",
        cache_fingerprint.AUX_CACHE_FORMAT_VERSION + 1,
    )
    assert _fp() != before


def _broadcast_fp(nav_files: list[Path]) -> str:
    return compute_broadcast_cache_fingerprint(
        nav_files=nav_files,
        canonical_grid_seconds=CANONICAL_AUX_GRID_SECONDS,
        aggregate_glonass_fdma=True,
    )


def _nav(folder: Path, name: str, content: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(content)
    return path


def test_broadcast_follows_the_content_not_the_path(tmp_path: Path) -> None:
    """Receivers and sites with the same navigation files share the entry."""
    a = _nav(tmp_path / "a", "FANG00AUT_R_20250010000_15M_00U_AA.nav", "records")
    b = _nav(tmp_path / "b", "INKR00AUT_R_20250010000_15M_00U_AA.nav", "records")

    assert _broadcast_fp([a]) == _broadcast_fp([b])


def test_broadcast_changed_file_gives_a_new_entry(tmp_path: Path) -> None:
    nav = _nav(tmp_path, "FANG00AUT_R_20250010000_15M_00U_AA.nav", "records")
    before = _broadcast_fp([nav])

    nav.write_text("records, revised")

    assert _broadcast_fp([nav]) != before


def test_broadcast_added_file_gives_a_new_entry(tmp_path: Path) -> None:
    first = _nav(tmp_path, "FANG00AUT_R_20250010000_15M_00U_AA.nav", "00:00")
    second = _nav(tmp_path, "FANG00AUT_R_20250010015_15M_00U_AA.nav", "00:15")

    assert _broadcast_fp([first, second]) != _broadcast_fp([first])


def test_broadcast_never_collides_with_precise(tmp_path: Path) -> None:
    assert _broadcast_fp([]) not in {
        _fp(ephemeris_source="broadcast", source_file_paths={}),
        _fp(ephemeris_source="precise", source_file_paths={}),
        _fp(),
    }


def test_broadcast_sensitive_to_aggregate_glonass_fdma(tmp_path: Path) -> None:
    nav = _nav(tmp_path, "FANG00AUT_R_20250010000_15M_00U_AA.nav", "records")
    kwargs = {"nav_files": [nav], "canonical_grid_seconds": 1.0}

    assert compute_broadcast_cache_fingerprint(
        **kwargs, aggregate_glonass_fdma=True
    ) != compute_broadcast_cache_fingerprint(**kwargs, aggregate_glonass_fdma=False)
