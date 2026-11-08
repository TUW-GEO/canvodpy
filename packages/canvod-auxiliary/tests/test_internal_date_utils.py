"""
Tests for internal date utilities.

Tests YYYYDOY class and GPS week conversion functions.
"""

import datetime
import operator
from pathlib import Path

import pytest

from canvod.utils.tools import YYYYDOY, get_gps_week_from_filename


class TestYYYYDOY:
    """Tests for YYYYDOY class."""

    def test_from_date(self):
        """Test creating YYYYDOY from datetime.date."""
        date = datetime.date(2024, 1, 15)
        yyyydoy = YYYYDOY.from_date(date)

        assert yyyydoy.year == 2024
        assert yyyydoy.doy == 15
        assert yyyydoy.date == date

    def test_from_str(self):
        """Test creating YYYYDOY from string."""
        yyyydoy = YYYYDOY.from_str("2024015")

        assert yyyydoy.year == 2024
        assert yyyydoy.doy == 15
        assert yyyydoy.date == datetime.date(2024, 1, 15)

    def test_from_int(self):
        """Test creating YYYYDOY from integer."""
        yyyydoy = YYYYDOY.from_int(2024015)

        assert yyyydoy.year == 2024
        assert yyyydoy.doy == 15

    def test_to_str(self):
        """Test converting YYYYDOY to string."""
        yyyydoy = YYYYDOY(year=2024, doy=15)
        assert yyyydoy.to_str() == "2024015"

    def test_invalid_doy_too_low(self):
        """Test that invalid DOY (< 1) raises ValidationError."""
        from pydantic_core import ValidationError

        with pytest.raises(ValidationError):
            YYYYDOY(year=2024, doy=0)

    def test_invalid_doy_too_high(self):
        """Test that invalid DOY (> 366) raises ValidationError."""
        from pydantic_core import ValidationError

        with pytest.raises(ValidationError):
            YYYYDOY(year=2024, doy=367)

    def test_invalid_str_format(self):
        """Test that invalid string format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid format"):
            YYYYDOY.from_str("2024")

    def test_equality(self):
        """Test YYYYDOY equality comparison."""
        yyyydoy1 = YYYYDOY(year=2024, doy=15)
        yyyydoy2 = YYYYDOY.from_str("2024015")

        assert yyyydoy1 == yyyydoy2

    def test_less_than(self):
        """Test YYYYDOY less than comparison."""
        yyyydoy1 = YYYYDOY(year=2024, doy=15)
        yyyydoy2 = YYYYDOY(year=2024, doy=20)

        assert yyyydoy1 < yyyydoy2
        assert operator.lt(yyyydoy2, yyyydoy1) is False

    def test_hashable(self):
        """Test that YYYYDOY is hashable."""
        yyyydoy1 = YYYYDOY(year=2024, doy=15)
        yyyydoy2 = YYYYDOY(year=2024, doy=20)

        # Should be able to add to set
        date_set = {yyyydoy1, yyyydoy2}
        assert len(date_set) == 2

    def test_gps_week_property(self):
        """Test GPS week calculation."""
        # GPS week 0 started on January 6, 1980
        yyyydoy = YYYYDOY.from_date(datetime.date(1980, 1, 6))
        assert yyyydoy.gps_week == 0

        # Test a known GPS week
        yyyydoy = YYYYDOY.from_date(datetime.date(2024, 1, 1))
        assert yyyydoy.gps_week > 2000  # Should be well past week 2000

    def test_gps_day_of_week_property(self):
        """Test GPS day of week calculation."""
        # January 6, 1980 was a Sunday (GPS day 0)
        yyyydoy = YYYYDOY.from_date(datetime.date(1980, 1, 6))
        assert yyyydoy.gps_day_of_week == 0


class TestGPSWeekFunctions:
    """Tests for GPS week conversion functions."""

    def test_gpsweekday_from_date(self):
        """Test gpsweekday with datetime.date."""
        date = datetime.date(1980, 1, 6)  # GPS epoch
        week, day = YYYYDOY.gpsweekday(date)

        assert week == 0
        assert day == 0

    def test_gpsweekday_from_string(self):
        """Test gpsweekday with string date."""
        week, day = YYYYDOY.gpsweekday("06-01-1980")

        assert week == 0
        assert day == 0

    def test_get_gps_week_from_sp3_filename(self):
        """Test extracting GPS week from SP3 filename."""
        filename = Path("COD0MGXFIN_20240150000_01D_05M_ORB.SP3")
        gps_week = get_gps_week_from_filename(filename)

        # 2024015 should map to a specific GPS week
        assert isinstance(gps_week, str)
        assert int(gps_week) > 2000

    def test_get_gps_week_from_clk_filename(self):
        """Test extracting GPS week from CLK filename."""
        filename = Path("COD0MGXFIN_20240150000_01D_30S_CLK.CLK")
        gps_week = get_gps_week_from_filename(filename)

        assert isinstance(gps_week, str)
        assert int(gps_week) > 2000

    def test_get_gps_week_invalid_extension(self):
        """Test that invalid file extension raises error."""
        filename = Path("invalid_file.txt")

        with pytest.raises(ValueError, match="Invalid file type"):
            get_gps_week_from_filename(filename)


class TestYYYDOYEdgeCases:
    """Test edge cases for YYYYDOY."""

    def test_leap_year_day_366(self):
        """Test that DOY 366 works in leap year."""
        yyyydoy = YYYYDOY(year=2024, doy=366)  # 2024 is a leap year
        assert yyyydoy.date == datetime.date(2024, 12, 31)

    def test_new_years_day(self):
        """Test January 1st (DOY 001)."""
        yyyydoy = YYYYDOY(year=2024, doy=1)
        assert yyyydoy.date == datetime.date(2024, 1, 1)

    def test_end_of_year_non_leap(self):
        """Test December 31st in non-leap year (DOY 365)."""
        yyyydoy = YYYYDOY(year=2023, doy=365)  # 2023 is not a leap year
        assert yyyydoy.date == datetime.date(2023, 12, 31)
