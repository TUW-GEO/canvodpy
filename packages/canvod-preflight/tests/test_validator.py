"""Tests for canvod.preflight.DataDirectoryValidator."""

from __future__ import annotations

from pathlib import Path

import pytest

from canvod.preflight import (
    DataDirectoryValidator,
    ReceiverNamingConfig,
    SiteNamingConfig,
)
from canvod.utils import testing

# Tests of the deprecated mapping and validation API, see test_deprecations.py.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


@pytest.fixture
def site_naming() -> SiteNamingConfig:
    return SiteNamingConfig(site_id=testing.SITE_ID, agency=testing.AGENCY)


@pytest.fixture
def receiver_naming() -> ReceiverNamingConfig:
    return ReceiverNamingConfig(
        receiver_number=1,
        source_pattern="auto",
        directory_layout="flat",
    )


@pytest.fixture
def validator() -> DataDirectoryValidator:
    return DataDirectoryValidator()


def _create_file(directory: Path, name: str) -> Path:
    f = directory / name
    f.write_bytes(b"\x00")
    return f


class TestValidationPasses:
    def test_valid_canonical_files(
        self, tmp_path, validator, site_naming, receiver_naming
    ):
        _create_file(tmp_path, "FANR01INK_R_20250010000_01D_05S_AA.rnx")
        _create_file(tmp_path, "FANR01INK_R_20250020000_01D_05S_AA.rnx")
        report = validator.validate_receiver(
            site_naming=site_naming,
            receiver_naming=receiver_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        assert report.is_valid
        assert len(report.matched) == 2

    def test_empty_directory_is_valid(
        self, tmp_path, validator, site_naming, receiver_naming
    ):
        """Truly empty directory: files_discovered=0 → is_valid=True (no data yet)."""
        report = validator.validate_receiver(
            site_naming=site_naming,
            receiver_naming=receiver_naming,
            receiver_type="canopy",
            receiver_base_dir=tmp_path,
        )
        assert report.is_valid
        assert len(report.matched) == 0
        assert report.files_discovered == 0


class TestZeroMatchBug:
    """P5.1: files discovered by globs but none parseable → is_valid=False."""

    def test_zero_match_with_discovered_files_is_invalid(
        self, tmp_path, validator, site_naming
    ):
        """Files found by glob but none parse → ValueError raised.

        A .25o file with a 3-char station prefix (needs 4) is picked up by
        the glob but fails all regex patterns → unmatched → validation error.
        This is the core P5.1 fix: before this fix, such a file would be
        silently skipped and validation would report success with 0 matched.
        """
        _create_file(tmp_path, "abc001a.25o")

        receiver_naming = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout="flat",
        )

        with pytest.raises(ValueError) as exc_info:
            validator.validate_receiver(
                site_naming=site_naming,
                receiver_naming=receiver_naming,
                receiver_type="canopy",
                receiver_base_dir=tmp_path,
            )

        assert "abc001a.25o" in str(exc_info.value)

    def test_zero_files_discovered_is_valid(self, tmp_path, validator, site_naming):
        """Layout mismatch: glob finds nothing (files_discovered=0) → is_valid=True.

        This is an unavoidable limitation: we can't distinguish an empty
        directory from a layout mismatch without scanning non-GNSS paths.
        files_discovered=0 explicitly conveys this to the caller.
        """
        # File at root level but layout says subdirs → globs look in nonexistent subdirs
        _create_file(tmp_path, "FANR01INK_R_20250010000_01D_05S_AA.rnx")

        receiver_naming = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout="yyddd_subdirs",
        )

        report = validator.validate_receiver(
            site_naming=site_naming,
            receiver_naming=receiver_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        assert report.is_valid
        assert report.files_discovered == 0
        assert len(report.matched) == 0


class TestPlainLanguageErrors:
    """P6: error messages use physical filenames, not canonical names."""

    def test_overlap_error_uses_physical_names(self, tmp_path, validator, site_naming):
        _create_file(tmp_path, "FANR01INK_R_20250010000_01D_05S_AA.rnx")
        _create_file(tmp_path, "FANR01INK_R_20250010000_15M_05S_AA.rnx")

        receiver_naming = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout="flat",
        )

        with pytest.raises(ValueError) as exc_info:
            validator.validate_receiver(
                site_naming=site_naming,
                receiver_naming=receiver_naming,
                receiver_type="reference",
                receiver_base_dir=tmp_path,
            )

        msg = str(exc_info.value)
        # Physical filename appears in error
        assert "FANR01INK_R_20250010000_01D_05S_AA.rnx" in msg
        # Error is plain language about overlap
        assert "overlap" in msg.lower()
        # Should NOT expose internal canonical name format (long internal string)
        assert "canonical" not in msg.lower()

    def test_unmatched_error_uses_physical_names(
        self, tmp_path, validator, site_naming, receiver_naming
    ):
        _create_file(tmp_path, "garbage.25o")

        with pytest.raises(ValueError) as exc_info:
            validator.validate_receiver(
                site_naming=site_naming,
                receiver_naming=receiver_naming,
                receiver_type="canopy",
                receiver_base_dir=tmp_path,
            )

        msg = str(exc_info.value)
        assert "garbage.25o" in msg
        assert "canonical" not in msg.lower()


class TestOverlapDetection:
    def test_daily_plus_subdaily_overlap(self, tmp_path, validator, site_naming):
        _create_file(tmp_path, "FANR01INK_R_20250010000_01D_05S_AA.rnx")
        _create_file(tmp_path, "FANR01INK_R_20250010000_15M_05S_AA.rnx")

        receiver_naming = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout="flat",
        )

        with pytest.raises(ValueError, match="overlap"):
            validator.validate_receiver(
                site_naming=site_naming,
                receiver_naming=receiver_naming,
                receiver_type="reference",
                receiver_base_dir=tmp_path,
            )

    def test_non_overlapping_files_pass(self, tmp_path, validator, site_naming):
        _create_file(tmp_path, "FANR01INK_R_20250010000_15M_05S_AA.rnx")
        _create_file(tmp_path, "FANR01INK_R_20250010015_15M_05S_AA.rnx")
        _create_file(tmp_path, "FANR01INK_R_20250010030_15M_05S_AA.rnx")

        receiver_naming = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout="flat",
        )

        report = validator.validate_receiver(
            site_naming=site_naming,
            receiver_naming=receiver_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        assert report.is_valid
        assert len(report.matched) == 3
