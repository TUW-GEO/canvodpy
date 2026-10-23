"""Pytest configuration for canvod-aux tests."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from canvod.utils import testing


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line(
        "markers", "network: marks tests that require network access"
    )
    config.addinivalue_line(
        "filterwarnings",
        "ignore:Remove `format_exc_info`:UserWarning:structlog",
    )


@pytest.fixture(scope="session")
def test_data_dir():
    """Fixture providing path to test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def sample_sp3_data():
    """
    Fixture providing sample SP3 dataset with sv dimension.

    Simulates raw SP3 data: (epoch: 96, sv: 4)
    """
    base_time = np.datetime64("2024-01-01T00:00:00")
    epochs = base_time + np.arange(96) * np.timedelta64(15, "m")
    svs = ["G01", "G02", "E01", "R01"]

    # Realistic satellite positions (ECEF, meters)
    pos_x = np.random.uniform(2e7, 3e7, size=(96, 4))
    pos_y = np.random.uniform(1e6, 5e6, size=(96, 4))
    pos_z = np.random.uniform(1e7, 2e7, size=(96, 4))

    # Velocities (m/s)
    vel_x = np.random.uniform(-3000, 3000, size=(96, 4))
    vel_y = np.random.uniform(-3000, 3000, size=(96, 4))
    vel_z = np.random.uniform(-3000, 3000, size=(96, 4))

    ds = xr.Dataset(
        {
            "X": (["epoch", "sv"], pos_x),
            "Y": (["epoch", "sv"], pos_y),
            "Z": (["epoch", "sv"], pos_z),
            "VX": (["epoch", "sv"], vel_x),
            "VY": (["epoch", "sv"], vel_y),
            "VZ": (["epoch", "sv"], vel_z),
        },
        coords={
            "epoch": epochs,
            "sv": svs,
        },
        attrs={
            "Created": "2024-01-01T00:00:00Z",
            "File Type": "SP3",
        },
    )

    return ds


@pytest.fixture
def sample_clk_data():
    """
    Fixture providing sample CLK dataset with sv dimension.

    Simulates raw CLK data: (epoch: 288, sv: 4)
    """
    base_time = np.datetime64("2024-01-01T00:00:00")
    epochs = base_time + np.arange(288) * np.timedelta64(5, "m")
    svs = ["G01", "G02", "E01", "R01"]

    # Clock bias in seconds
    clock_bias = np.random.uniform(-1e-6, 1e-6, size=(288, 4))

    ds = xr.Dataset(
        {
            "clock_bias": (["epoch", "sv"], clock_bias),
        },
        coords={
            "epoch": epochs,
            "sv": svs,
        },
        attrs={
            "Created": "2024-01-01T00:00:00Z",
            "File Type": "CLK",
        },
    )

    return ds


@pytest.fixture
def sample_rinex_data():
    """
    Fixture providing sample RINEX dataset with sid dimension.

    Simulates RINEX data: (epoch: 2880, sid: 48)
    48 unique signal IDs from 4 constellations.
    """
    base_time = np.datetime64("2024-01-01T00:00:00")
    epochs = base_time + np.arange(2880) * np.timedelta64(30, "s")

    # Generate 48 UNIQUE signal IDs across 4 constellations
    sids = [
        # GPS (12 sids: 4 satellites × 3 signals)
        "G01|L1|C",
        "G01|L2|W",
        "G01|L5|I",
        "G02|L1|C",
        "G02|L2|W",
        "G02|L5|I",
        "G03|L1|C",
        "G03|L2|W",
        "G03|L5|I",
        "G04|L1|C",
        "G04|L2|W",
        "G04|L5|I",
        # Galileo (12 sids: 4 satellites × 3 signals)
        "E01|E1|C",
        "E01|E5a|Q",
        "E01|E5b|I",
        "E02|E1|C",
        "E02|E5a|Q",
        "E02|E5b|I",
        "E03|E1|C",
        "E03|E5a|Q",
        "E03|E5b|I",
        "E04|E1|C",
        "E04|E5a|Q",
        "E04|E5b|I",
        # GLONASS (12 sids: 4 satellites × 3 signals)
        "R01|G1|C",
        "R01|G2|P",
        "R01|G3|I",
        "R02|G1|C",
        "R02|G2|P",
        "R02|G3|I",
        "R03|G1|C",
        "R03|G2|P",
        "R03|G3|I",
        "R04|G1|C",
        "R04|G2|P",
        "R04|G3|I",
        # BeiDou (12 sids: 4 satellites × 3 signals)
        "C01|B1I|I",
        "C01|B3I|I",
        "C01|B2a|I",
        "C02|B1I|I",
        "C02|B3I|I",
        "C02|B2a|I",
        "C03|B1I|I",
        "C03|B3I|I",
        "C03|B2a|I",
        "C04|B1I|I",
        "C04|B3I|I",
        "C04|B2a|I",
    ]

    # Verify uniqueness
    assert len(sids) == 48
    assert len(set(sids)) == 48, "sids must be unique"

    # SNR data
    snr_data = np.random.uniform(30, 55, size=(2880, 48))

    ds = xr.Dataset(
        {
            "SNR": (["epoch", "sid"], snr_data),
        },
        coords={
            "epoch": epochs,
            "sid": sids,
            "sv": (["sid"], [sid.split("|")[0] for sid in sids]),
            "band": (["sid"], [sid.split("|")[1] for sid in sids]),
            "code": (["sid"], [sid.split("|")[2] for sid in sids]),
        },
        attrs={
            "Created": "2024-01-01T00:00:00Z",
            "File Hash": "abc123",
            "APPROX POSITION X": testing.ECEF_X,
            "APPROX POSITION Y": testing.ECEF_Y,
            "APPROX POSITION Z": testing.ECEF_Z,
        },
    )

    return ds


@pytest.fixture
def sample_preprocessed_sp3():
    """
    Fixture providing sample preprocessed SP3 with sid dimension.

    Output after preprocessing: (epoch: 96, sid: 48)
    Must match sample_rinex_data sid structure.
    """
    base_time = np.datetime64("2024-01-01T00:00:00")
    epochs = base_time + np.arange(96) * np.timedelta64(15, "m")

    # Same 48 unique sids as sample_rinex_data
    sids = [
        # GPS (12 sids: 4 satellites × 3 signals)
        "G01|L1|C",
        "G01|L2|W",
        "G01|L5|I",
        "G02|L1|C",
        "G02|L2|W",
        "G02|L5|I",
        "G03|L1|C",
        "G03|L2|W",
        "G03|L5|I",
        "G04|L1|C",
        "G04|L2|W",
        "G04|L5|I",
        # Galileo (12 sids: 4 satellites × 3 signals)
        "E01|E1|C",
        "E01|E5a|Q",
        "E01|E5b|I",
        "E02|E1|C",
        "E02|E5a|Q",
        "E02|E5b|I",
        "E03|E1|C",
        "E03|E5a|Q",
        "E03|E5b|I",
        "E04|E1|C",
        "E04|E5a|Q",
        "E04|E5b|I",
        # GLONASS (12 sids: 4 satellites × 3 signals)
        "R01|G1|C",
        "R01|G2|P",
        "R01|G3|I",
        "R02|G1|C",
        "R02|G2|P",
        "R02|G3|I",
        "R03|G1|C",
        "R03|G2|P",
        "R03|G3|I",
        "R04|G1|C",
        "R04|G2|P",
        "R04|G3|I",
        # BeiDou (12 sids: 4 satellites × 3 signals)
        "C01|B1I|I",
        "C01|B3I|I",
        "C01|B2a|D",
        "C02|B1I|I",
        "C02|B3I|I",
        "C02|B2a|P",
        "C03|B1I|I",
        "C03|B3I|I",
        "C03|B2a|X",
        "C04|B1I|I",
        "C04|B3I|I",
        "C04|B2a|P",
    ]

    assert len(sids) == 48
    assert len(set(sids)) == 48, "sids must be unique"

    pos_x = np.random.uniform(2e7, 3e7, size=(96, 48))
    pos_y = np.random.uniform(1e6, 5e6, size=(96, 48))
    pos_z = np.random.uniform(1e7, 2e7, size=(96, 48))

    ds = xr.Dataset(
        {
            "X": (["epoch", "sid"], pos_x),
            "Y": (["epoch", "sid"], pos_y),
            "Z": (["epoch", "sid"], pos_z),
        },
        coords={
            "epoch": epochs,
            "sid": sids,
        },
        attrs={
            "Created": "2024-01-01T00:00:00Z",
        },
    )

    return ds


@pytest.fixture
def ecef_position():
    """Fixture providing the made-up site's ECEF position (Bloemfontein)."""
    from canvod.auxiliary import ECEFPosition

    return ECEFPosition(x=testing.ECEF_X, y=testing.ECEF_Y, z=testing.ECEF_Z)


@pytest.fixture
def geodetic_position():
    """Fixture providing sample geodetic position.

    The made-up site's position (Bloemfontein), the same point as the
    ``ecef_position`` fixture.
    """
    from canvod.auxiliary import GeodeticPosition

    return GeodeticPosition(
        lat=testing.LATITUDE, lon=testing.LONGITUDE, alt=testing.ALTITUDE_M
    )
