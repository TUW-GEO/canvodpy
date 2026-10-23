"""Test core gnss_specs modules: constants, exceptions, models, utils, metadata."""

import pytest

from canvod.readers.gnss_specs import constants, exceptions, models, utils


class TestExceptions:
    """Test custom exception classes."""

    def test_rinex_error(self):
        """Test base RinexError."""
        err = exceptions.RinexError("Test error")
        assert str(err) == "Test error"
        assert isinstance(err, Exception)

    def test_missing_epoch_error(self):
        """Test MissingEpochError."""
        err = exceptions.MissingEpochError("Missing epoch")
        assert isinstance(err, exceptions.RinexError)

    def test_incomplete_epoch_error(self):
        """Test IncompleteEpochError."""
        err = exceptions.IncompleteEpochError("Incomplete")
        assert isinstance(err, exceptions.RinexError)

    def test_invalid_epoch_error(self):
        """Test InvalidEpochError."""
        err = exceptions.InvalidEpochError("Invalid")
        assert isinstance(err, exceptions.RinexError)


class TestConstants:
    """Test constants module."""

    def test_ureg_exists(self):
        """Test unit registry is available."""
        assert hasattr(constants, "UREG")
        assert constants.UREG is not None

    def test_custom_units(self):
        """Test custom units are defined."""
        # dBHz unit
        dbhz = constants.UREG.dBHz
        assert dbhz is not None

        # dB unit
        db = constants.UREG.dB
        assert db is not None

    def test_speed_of_light(self):
        """Test speed of light constant."""
        c = constants.SPEEDOFLIGHT
        assert c.magnitude == pytest.approx(299792458.0)
        assert str(c.units) == "meter / second"

    def test_epoch_record_indicator(self):
        """Test epoch record indicator."""
        assert constants.EPOCH_RECORD_INDICATOR == ">"

    def test_sampling_intervals(self):
        """Test sampling interval constants."""
        assert len(constants.SEPTENTRIO_SAMPLING_INTERVALS) > 0
        assert len(constants.IGS_RNX_DUMP_INTERVALS) > 0


class TestModels:
    """Test Pydantic validation models."""

    def test_observation_creation(self):
        """Test Observation model."""
        obs = models.Observation(obs_type="S", value=45.0, lli=None, ssi=5)

        assert obs.value == 45.0
        assert obs.ssi == 5

    def test_satellite_creation(self):
        """Test Satellite model."""
        sat = models.Satellite(sv="G01")
        assert sat.sv == "G01"
        assert len(sat.observations) == 0

    def test_satellite_invalid_sv(self):
        """Test satellite validation."""
        with pytest.raises(ValueError):
            models.Satellite(sv="INVALID")

    def test_satellite_add_observation(self):
        """Test adding observations to satellite."""
        sat = models.Satellite(sv="G01")
        obs = models.Observation(obs_type="S", value=45.0, lli=None, ssi=5)

        sat.add_observation(obs)
        assert len(sat.observations) == 1

    def test_epoch_creation(self):
        """Test Epoch model."""
        from datetime import datetime

        epoch = models.Epoch(timestamp=datetime(2025, 1, 1, 0, 0, 0), num_satellites=1)

        assert epoch.num_satellites == 1
        assert len(epoch.satellites) == 0


class TestUtils:
    """Test utility functions."""

    def test_isfloat_valid(self):
        """Test isfloat with valid values."""
        assert utils.isfloat("3.14") is True
        assert utils.isfloat("-2.5") is True
        assert utils.isfloat("0") is True

    def test_isfloat_invalid(self):
        """Test isfloat with invalid values."""
        assert utils.isfloat("not_a_number") is False
        assert utils.isfloat("") is False

    def test_file_hash(self, tmp_path):
        """Test file hash generation."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        hash1 = utils.file_hash(test_file)
        hash2 = utils.file_hash(test_file)

        # Hash should be consistent
        assert hash1 == hash2
        assert len(hash1) == 16  # Short hash

    def test_get_version_from_pyproject(self):
        """Test version extraction from pyproject.toml."""
        # This will work if pyproject.toml exists in standard location
        try:
            version = utils.get_version_from_pyproject()
            assert version is not None
            assert isinstance(version, str)
        except FileNotFoundError:
            pytest.skip("pyproject.toml not found in expected location")


class TestMetadata:
    """Test metadata definitions."""

    def test_coords_metadata_exists(self):
        """Test coordinate metadata is defined."""
        from canvod.readers.gnss_specs import metadata

        assert hasattr(metadata, "COORDS_METADATA")
        assert isinstance(metadata.COORDS_METADATA, dict)

        # Check required coordinates
        required = ["epoch", "sid", "sv", "system", "band", "code"]
        for coord in required:
            assert coord in metadata.COORDS_METADATA

    def test_observables_metadata_exists(self):
        """Test observables metadata is defined."""
        from canvod.readers.gnss_specs import metadata

        assert hasattr(metadata, "OBSERVABLES_METADATA")
        assert isinstance(metadata.OBSERVABLES_METADATA, dict)

        # Check common observables
        observables = ["Pseudorange", "Phase", "Doppler"]
        for obs in observables:
            assert obs in metadata.OBSERVABLES_METADATA

    def test_dtypes_exists(self):
        """Test data types are defined."""
        from canvod.readers.gnss_specs import metadata

        assert hasattr(metadata, "DTYPES")
        assert isinstance(metadata.DTYPES, dict)


class TestContractConstants:
    """Test contract constants and validate_dataset()."""

    def test_constants_importable(self):
        """Test that contract constants are importable."""
        from canvod.readers.base import (
            DEFAULT_REQUIRED_VARS,
            REQUIRED_ATTRS,
            REQUIRED_COORDS,
            REQUIRED_DIMS,
        )

        assert REQUIRED_DIMS == ("epoch", "sid")
        assert "epoch" in REQUIRED_COORDS
        assert "File Hash" in REQUIRED_ATTRS
        assert "SNR" in DEFAULT_REQUIRED_VARS

    def test_validate_dataset_collects_all_errors(self):
        """Test validate_dataset reports all violations at once."""
        import xarray as xr

        from canvod.readers.base import validate_dataset

        empty_ds = xr.Dataset()
        with pytest.raises(ValueError, match="Dataset validation failed") as exc_info:
            validate_dataset(empty_ds)

        error_msg = str(exc_info.value)
        # Should mention missing dims, coords, vars, and attrs
        assert "dimensions" in error_msg.lower()
        assert "coordinate" in error_msg.lower()
        assert "attributes" in error_msg.lower()

    def test_validate_dataset_passes_valid(self):
        """Test validate_dataset succeeds on a valid dataset."""
        import numpy as np
        import xarray as xr

        from canvod.readers.base import validate_dataset

        sids = np.array(["G01|L1|C"], dtype=object)
        epochs = [np.datetime64("2024-01-01T00:00:00", "ns")]
        ds = xr.Dataset(
            data_vars={"SNR": (("epoch", "sid"), np.array([[42.0]], dtype="float32"))},
            coords={
                "epoch": ("epoch", epochs),
                "sid": ("sid", sids),
                "sv": ("sid", np.array(["G01"], dtype=object)),
                "system": ("sid", np.array(["G"], dtype=object)),
                "band": ("sid", np.array(["L1"], dtype=object)),
                "code": ("sid", np.array(["C"], dtype=object)),
                "freq_center": ("sid", np.array([1575.42], dtype="float32")),
                "freq_min": ("sid", np.array([1560.0], dtype="float32")),
                "freq_max": ("sid", np.array([1590.0], dtype="float32")),
            },
            attrs={
                "Created": "2024-01-01",
                "Software": "test",
                "Institution": "test",
                "File Hash": "abc123",
            },
        )
        # Should not raise
        validate_dataset(ds)


class TestVodContract:
    """Test validate_vod_dataset()."""

    @staticmethod
    def _vod_ds():
        import numpy as np
        import xarray as xr

        from canvod.readers.base import SignalID
        from canvod.readers.builder import sid_coords
        from canvod.readers.gnss_specs.signals import SignalIDMapper

        signals = [SignalID(sv="G01", band="L1", code="C")]
        values = np.array([[0.4]])
        return xr.Dataset(
            {
                "VOD": (("epoch", "sid"), values),
                "phi": (("epoch", "sid"), values),
                "theta": (("epoch", "sid"), values),
            },
            coords={
                "epoch": [np.datetime64("2024-01-01T00:00:00", "ns")],
                **sid_coords(signals, mapper=SignalIDMapper()),
            },
        )

    def test_valid_vod_dataset_passes(self):
        from canvod.readers.base import validate_vod_dataset

        validate_vod_dataset(self._vod_ds())

    def test_no_reader_attrs_required(self):
        """VOD datasets carry no file hash: the reader attributes are not required."""
        from canvod.readers.base import validate_vod_dataset

        ds = self._vod_ds()
        assert not ds.attrs
        validate_vod_dataset(ds)

    def test_collects_all_errors(self):
        from canvod.readers.base import validate_vod_dataset

        ds = self._vod_ds().drop_vars(["theta", "freq_center"])
        ds["VOD"] = ds["VOD"].transpose("sid", "epoch")
        with pytest.raises(ValueError, match="VOD dataset validation failed") as exc:
            validate_vod_dataset(ds)
        msg = str(exc.value)
        assert "theta" in msg
        assert "freq_center" in msg
        assert "wrong dimensions" in msg

    def test_gnssvod_shaped_dataset_fails(self):
        """A dataset on (Epoch, SV) with angles in degrees is not a canvodpy VOD dataset."""
        import numpy as np
        import xarray as xr

        from canvod.readers.base import validate_vod_dataset

        ds = xr.Dataset(
            {
                "VOD_L1": (("Epoch", "SV"), np.array([[0.4]])),
                "Elevation": (("Epoch", "SV"), np.array([[30.0]])),
            },
            coords={"Epoch": [np.datetime64("2024-01-01")], "SV": ["G01"]},
        )
        with pytest.raises(ValueError, match="Missing required dimensions"):
            validate_vod_dataset(ds)
