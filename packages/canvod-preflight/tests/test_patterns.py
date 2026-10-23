"""Tests for canvod.preflight.patterns."""

import pytest

from canvod.preflight.patterns import (
    AUTO_PATTERN_ORDER,
    BUILTIN_PATTERNS,
    hour_letter_to_int,
    match_pattern,
    resolve_year_from_yy,
)

# Tests of the deprecated mapping and validation API, see test_deprecations.py.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


class TestHourLetterToInt:
    def test_a_is_zero(self):
        assert hour_letter_to_int("a") == 0

    def test_x_is_23(self):
        assert hour_letter_to_int("x") == 23

    def test_zero_char_is_zero(self):
        assert hour_letter_to_int("0") == 0

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid hour letter"):
            hour_letter_to_int("z")

    def test_uppercase_accepted(self):
        assert hour_letter_to_int("B") == 1


class TestResolveYearFromYy:
    def test_year_00(self):
        assert resolve_year_from_yy(0) == 2000

    def test_year_25(self):
        assert resolve_year_from_yy(25) == 2025

    def test_year_79(self):
        assert resolve_year_from_yy(79) == 2079

    def test_year_80(self):
        assert resolve_year_from_yy(80) == 1980

    def test_year_99(self):
        assert resolve_year_from_yy(99) == 1999


class TestBuiltinPatterns:
    def test_all_auto_patterns_exist(self):
        for name in AUTO_PATTERN_ORDER:
            assert name in BUILTIN_PATTERNS

    def test_canvod_pattern_matches(self):
        pat = BUILTIN_PATTERNS["canvod"]
        m = pat.regex.match("FANR01INK_R_20250010000_01D_05S_AA.rnx")
        assert m is not None
        assert m.group("year") == "2025"
        assert m.group("doy") == "001"
        assert m.group("hour") == "00"
        assert m.group("minute") == "00"
        assert m.group("period") == "01D"
        assert m.group("sampling") == "05S"

    def test_canvod_pattern_with_compression(self):
        pat = BUILTIN_PATTERNS["canvod"]
        m = pat.regex.match("ORTA01MEA_R_20250010000_01D_01S_AA.rnx.zip")
        assert m is not None

    def test_rinex_v3_long_matches(self):
        pat = BUILTIN_PATTERNS["rinex_v3_long"]
        m = pat.regex.match("FANA00INK_R_20250010000_01D_05S_MO.rnx")
        assert m is not None
        assert m.group("station") == "FANA"
        assert m.group("year") == "2025"
        assert m.group("doy") == "001"
        assert m.group("sampling") == "05S"

    def test_rinex_v3_long_with_compression(self):
        pat = BUILTIN_PATTERNS["rinex_v3_long"]
        m = pat.regex.match("FANA00INK_R_20250010000_01D_05S_MO.rnx.gz")
        assert m is not None

    def test_rinex_v2_short_matches(self):
        pat = BUILTIN_PATTERNS["rinex_v2_short"]
        m = pat.regex.match("rosl001a.25o")
        assert m is not None
        assert m.group("station") == "rosl"
        assert m.group("doy") == "001"
        assert m.group("hour_letter") == "a"
        assert m.group("yy") == "25"

    def test_rinex_v2_short_compressed(self):
        pat = BUILTIN_PATTERNS["rinex_v2_short"]
        m = pat.regex.match("rosl001a.25o.gz")
        assert m is not None

    def test_septentrio_sbf_matches(self):
        pat = BUILTIN_PATTERNS["septentrio_sbf"]
        m = pat.regex.match("rref001a00.25_")
        assert m is not None
        assert m.group("station") == "rref"
        assert m.group("doy") == "001"
        assert m.group("hour_letter") == "a"
        assert m.group("minute") == "00"
        assert m.group("yy") == "25"


class TestMatchPattern:
    def test_auto_matches_canvod(self):
        result = match_pattern("FANR01INK_R_20250010000_01D_05S_AA.rnx")
        assert result is not None
        pat, m = result
        assert pat.name == "canvod"

    def test_auto_matches_rinex_v2(self):
        result = match_pattern("rosl001a.25o")
        assert result is not None
        pat, m = result
        assert pat.name == "rinex_v2_short"

    def test_auto_matches_septentrio(self):
        result = match_pattern("rref001a00.25_")
        assert result is not None
        pat, m = result
        assert pat.name == "septentrio_sbf"

    def test_auto_returns_none_for_unknown(self):
        result = match_pattern("random_file.txt")
        assert result is None

    def test_specific_pattern_name(self):
        result = match_pattern("rosl001a.25o", "rinex_v2_short")
        assert result is not None
        pat, m = result
        assert pat.name == "rinex_v2_short"

    def test_specific_pattern_no_match(self):
        result = match_pattern("rosl001a.25o", "canvod")
        assert result is None

    def test_unknown_pattern_raises(self):
        with pytest.raises(ValueError, match="Unknown pattern"):
            match_pattern("file.txt", "nonexistent")

    def test_rinex_v3_long_auto_match(self):
        # A RINEX v3 long name that is NOT canvod-compliant
        # (different station code pattern: 4-char station + monument + country)
        result = match_pattern("FANA00INK_R_20250010000_01D_05S_MO.rnx")
        assert result is not None
        # Should match either canvod or rinex_v3_long (both have overlapping regex)
        assert result[0].name in ("canvod", "rinex_v3_long")
