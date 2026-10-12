"""Tests for canvod.preflight.convention."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from canvod.preflight.convention import (
    CanVODFilename,
    FileType,
    ReceiverType,
    _duration_to_timedelta,
)
from canvod.utils import testing


class TestDurationToTimedelta:
    def test_seconds(self):
        assert _duration_to_timedelta("05S") == timedelta(seconds=5)

    def test_minutes(self):
        assert _duration_to_timedelta("15M") == timedelta(minutes=15)

    def test_hours(self):
        assert _duration_to_timedelta("01H") == timedelta(hours=1)

    def test_days(self):
        assert _duration_to_timedelta("01D") == timedelta(days=1)


class TestReceiverType:
    def test_reference_value(self):
        assert ReceiverType.REFERENCE.value == "R"

    def test_active_value(self):
        assert ReceiverType.ACTIVE.value == "A"


class TestFileType:
    def test_rnx(self):
        assert FileType.RNX.value == "rnx"

    def test_sbf(self):
        assert FileType.SBF.value == "sbf"

    def test_ubx(self):
        assert FileType.UBX.value == "ubx"

    def test_nmea(self):
        assert FileType.NMEA.value == "nmea"


class TestCanVODFilenameConstruction:
    def test_minimal_construction(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        assert f.site == testing.SITE_ID
        assert f.receiver_type == ReceiverType.REFERENCE
        assert f.receiver_number == 1
        assert f.agency == testing.AGENCY
        assert f.year == 2025
        assert f.doy == 1
        assert f.hour == 0
        assert f.minute == 0
        assert f.period == "01D"
        assert f.sampling == "05S"
        assert f.content == "AA"
        assert f.file_type == FileType.RNX
        assert f.compression is None

    def test_full_construction(self):
        f = CanVODFilename(
            site=testing.OTHER_SITE_ID,
            receiver_type=ReceiverType.ACTIVE,
            receiver_number=1,
            agency=testing.OTHER_AGENCY,
            year=2025,
            doy=1,
            hour=0,
            minute=0,
            period="01D",
            sampling="01S",
            content="AA",
            file_type=FileType.RNX,
            compression="zip",
        )
        assert f.name == "ORTA01MEA_R_20250010000_01D_01S_AA.rnx.zip"

    def test_lowercase_site_rejected(self):
        with pytest.raises(ValidationError):
            CanVODFilename(
                site="ros",
                receiver_type=ReceiverType.REFERENCE,
                receiver_number=1,
                agency="tuw",
                year=2025,
                doy=1,
            )

    def test_frozen(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        with pytest.raises(AttributeError):
            f.site = testing.OTHER_SITE_ID

    def test_invalid_site_length(self):
        with pytest.raises(ValidationError):
            CanVODFilename(
                site="FANX",
                receiver_type=ReceiverType.REFERENCE,
                receiver_number=1,
                agency=testing.AGENCY,
                year=2025,
                doy=1,
            )

    def test_receiver_number_bounds(self):
        with pytest.raises(ValidationError):
            CanVODFilename(
                site=testing.SITE_ID,
                receiver_type=ReceiverType.REFERENCE,
                receiver_number=0,
                agency=testing.AGENCY,
                year=2025,
                doy=1,
            )
        with pytest.raises(ValidationError):
            CanVODFilename(
                site=testing.SITE_ID,
                receiver_type=ReceiverType.REFERENCE,
                receiver_number=100,
                agency=testing.AGENCY,
                year=2025,
                doy=1,
            )


class TestCanVODFilenameProperties:
    def test_name_no_compression(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        assert f.name == "FANR01INK_R_20250010000_01D_05S_AA.rnx"

    def test_name_with_compression(self):
        f = CanVODFilename(
            site=testing.OTHER_SITE_ID,
            receiver_type=ReceiverType.ACTIVE,
            receiver_number=1,
            agency=testing.OTHER_AGENCY,
            year=2025,
            doy=1,
            sampling="01S",
            compression="zip",
        )
        assert f.name == "ORTA01MEA_R_20250010000_01D_01S_AA.rnx.zip"

    def test_stem_no_compression(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        assert f.stem == f.name

    def test_stem_with_compression(self):
        f = CanVODFilename(
            site=testing.OTHER_SITE_ID,
            receiver_type=ReceiverType.ACTIVE,
            receiver_number=1,
            agency=testing.OTHER_AGENCY,
            year=2025,
            doy=1,
            sampling="01S",
            compression="zip",
        )
        assert f.stem == "ORTA01MEA_R_20250010000_01D_01S_AA.rnx"

    def test_sampling_interval(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
            sampling="05S",
        )
        assert f.sampling_interval == timedelta(seconds=5)

    def test_batch_duration(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
            period="01D",
        )
        assert f.batch_duration == timedelta(days=1)

    def test_str(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        assert str(f) == f.name


class TestCanVODFilenameFromFilename:
    @pytest.mark.parametrize(
        "filename",
        [
            "ORTA01MEA_R_20250010000_01D_01S_AA.rnx.zip",
            "FANR01INK_R_20250010000_01D_05S_AA.rnx",
            "FANR35INK_R_20232221530_15M_05S_AA.sbf",
        ],
    )
    def test_round_trip(self, filename):
        f = CanVODFilename.from_filename(filename)
        assert f.name == filename

    def test_strips_directory_prefix(self):
        f = CanVODFilename.from_filename(
            "/some/path/FANR01INK_R_20250010000_01D_05S_AA.rnx"
        )
        assert f.name == "FANR01INK_R_20250010000_01D_05S_AA.rnx"

    def test_invalid_filename_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            CanVODFilename.from_filename("not_a_valid_filename.txt")

    def test_sbf_file_type(self):
        f = CanVODFilename.from_filename("FANR35INK_R_20232221530_15M_05S_AA.sbf")
        assert f.file_type == FileType.SBF
        assert f.receiver_number == 35
        assert f.hour == 15
        assert f.minute == 30
        assert f.period == "15M"

    def test_ubx_file_type(self):
        f = CanVODFilename.from_filename("FANA01INK_R_20250010000_01D_01S_AA.ubx")
        assert f.file_type == FileType.UBX

    def test_nmea_file_type(self):
        f = CanVODFilename.from_filename("FANA01INK_R_20250010000_01D_01S_AA.nmea")
        assert f.file_type == FileType.NMEA

    def test_compression_empty_string_normalized(self):
        f = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
            compression="",
        )
        assert f.compression is None
