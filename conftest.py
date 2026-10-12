"""Pytest configuration for canvodpy workspace."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from canvod.config import loader
from canvod.utils import testing

# Existing submodule paths
TEST_DATA_ROOT = Path(__file__).parent / "packages/canvod-readers/tests/test_data"
DEMO_ROOT = Path(__file__).parent / "demo"


# ============================================================================
# Settings: made-up, never the user's own
# ============================================================================


@pytest.fixture(autouse=True)
def _made_up_settings(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Code that loads the settings itself reads the made-up ones.

    Never the user's own ``config/canvod-settings.yaml`` (CI has none).
    A test that needs other settings sets ``CANVOD_CONFIG_DIR`` itself.
    The cache is cleared because tests change the settings object. The
    cached function is kept, because a test may replace it with a plain one
    that is still in place when this fixture ends.
    """
    folder = tmp_path_factory.getbasetemp() / "made-up-settings"
    if not folder.exists():
        testing.write_settings(folder)
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(folder))
    monkeypatch.delenv("CANVOD_CONFIG_FILE", raising=False)
    cached = loader._load_config_cached
    cached.cache_clear()
    yield
    cached.cache_clear()


# ============================================================================
# Dask Shutdown Noise Suppression
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def _suppress_dask_shutdown_noise():
    """Silence Dask nanny/worker loggers during pytest teardown.

    Dask's nanny runs background threads that may try to log after pytest has
    closed ``sys.stderr``, raising ``ValueError: I/O operation on closed file``.
    Disabling the ``distributed`` logger hierarchy in the teardown phase
    prevents this.
    """
    yield
    for name in ("distributed", "distributed.nanny", "distributed.worker"):
        logging.getLogger(name).disabled = True


# ============================================================================
# Test Data Fixtures (canvodpy-test-data submodule)
# ============================================================================


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Root directory for test data.

    Location: packages/canvod-readers/tests/test_data
    Repository: https://github.com/nfb2021/canvodpy-test-data.git
    Purpose: Validation testing with falsified/corrupted files
    """
    if not TEST_DATA_ROOT.exists():
        pytest.skip(
            "Test data submodule not initialized. Run: "
            "git submodule update --init packages/canvod-readers/tests/test_data"
        )
    return TEST_DATA_ROOT


@pytest.fixture(scope="session")
def valid_test_data_dir(test_data_dir: Path) -> Path:
    """Valid test data directory."""
    return test_data_dir / "valid"


@pytest.fixture(scope="session")
def valid_rinex_dir(valid_test_data_dir: Path) -> Path:
    """Directory containing valid RINEX test files (Rosalia site)."""
    return valid_test_data_dir / "rinex_v3_04/01_Rosalia"


@pytest.fixture(scope="session")
def valid_aux_dir(valid_test_data_dir: Path) -> Path:
    """Directory containing valid auxiliary test files."""
    return valid_test_data_dir / "aux_data"


@pytest.fixture
def rosalia_reference_test_rinex(valid_rinex_dir: Path) -> Path:
    """Rosalia reference RINEX file from test data."""
    rinex_dir = valid_rinex_dir / "01_reference/01_GNSS/01_raw"
    if not rinex_dir.exists():
        pytest.skip(f"RINEX directory not found: {rinex_dir}")
    # Find any RINEX file (*.rnx, *.RNX, *.o, *.[0-9][0-9]o, etc.)
    files = (
        list(rinex_dir.rglob("*.[0-9][0-9]o"))
        + list(rinex_dir.glob("*.rnx"))
        + list(rinex_dir.glob("*.RNX"))
    )
    if not files:
        pytest.skip(f"No RINEX files in {rinex_dir}")
    return files[0]


@pytest.fixture
def rosalia_canopy_test_rinex(valid_rinex_dir: Path) -> Path:
    """Rosalia canopy RINEX file from test data."""
    rinex_dir = valid_rinex_dir / "02_canopy/01_GNSS/01_raw"
    if not rinex_dir.exists():
        pytest.skip(f"RINEX directory not found: {rinex_dir}")
    # Find any RINEX file
    files = (
        list(rinex_dir.rglob("*.[0-9][0-9]o"))
        + list(rinex_dir.glob("*.rnx"))
        + list(rinex_dir.glob("*.RNX"))
    )
    if not files:
        pytest.skip(f"No RINEX files in {rinex_dir}")
    return files[0]


@pytest.fixture(scope="session")
def corrupted_rinex_dir(test_data_dir: Path) -> Path:
    """Directory containing corrupted RINEX files for error testing."""
    return test_data_dir / "corrupted" / "rinex"


@pytest.fixture(scope="session")
def corrupted_aux_dir(test_data_dir: Path) -> Path:
    """Directory containing corrupted auxiliary files for error testing."""
    return test_data_dir / "corrupted" / "aux"


@pytest.fixture(scope="session")
def edge_case_dir(test_data_dir: Path) -> Path:
    """Directory containing edge case test files."""
    return test_data_dir / "edge_cases"


@pytest.fixture
def sample_sp3_file(valid_aux_dir: Path) -> Path:
    """Path to a standard valid SP3 file."""
    sp3_dir = valid_aux_dir / "01_SP3"
    if not sp3_dir.exists():
        pytest.skip(f"SP3 directory not found: {sp3_dir}")
    files = list(sp3_dir.glob("*.SP3")) + list(sp3_dir.glob("*.sp3"))
    if not files:
        pytest.skip(f"No SP3 files in {sp3_dir}")
    return files[0]


@pytest.fixture
def sample_clk_file(valid_aux_dir: Path) -> Path:
    """Path to a standard valid CLK file."""
    clk_dir = valid_aux_dir / "02_CLK"
    if not clk_dir.exists():
        pytest.skip(f"CLK directory not found: {clk_dir}")
    files = list(clk_dir.glob("*.CLK")) + list(clk_dir.glob("*.clk"))
    if not files:
        pytest.skip(f"No CLK files in {clk_dir}")
    return files[0]


# Mark for tests that require test data
requires_test_data = pytest.mark.skipif(
    not TEST_DATA_ROOT.exists(), reason="Test data submodule not initialized"
)


# ============================================================================
# Demo Data Fixtures (canvodpy-demo submodule)
# ============================================================================


@pytest.fixture(scope="session")
def demo_dir() -> Path:
    """Root directory for demo data.

    Location: demo
    Repository: https://github.com/nfb2021/canvodpy-demo.git
    Purpose: Clean real-world data for demos and documentation
    """
    if not DEMO_ROOT.exists():
        pytest.skip(
            "Demo submodule not initialized. Run: git submodule update --init demo"
        )
    return DEMO_ROOT


@pytest.fixture(scope="session")
def demo_data_dir(demo_dir: Path) -> Path:
    """Demo data directory."""
    return demo_dir / "data"


@pytest.fixture(scope="session")
def demo_rosalia_dir(demo_data_dir: Path) -> Path:
    """Rosalia demo data directory."""
    return demo_data_dir / "01_Rosalia"


@pytest.fixture(scope="session")
def demo_aux_dir(demo_data_dir: Path) -> Path:
    """Demo auxiliary files directory."""
    return demo_data_dir / "00_aux_files"


@pytest.fixture
def demo_rosalia_reference(demo_rosalia_dir: Path) -> Path:
    """Demo Rosalia reference RINEX file (first available)."""
    rinex_dir = demo_rosalia_dir / "01_reference/01_GNSS/01_raw"
    if not rinex_dir.exists():
        pytest.skip(f"RINEX directory not found: {rinex_dir}")
    # Find any RINEX file in any subdirectory (25001, 25002, etc.)
    files = (
        list(rinex_dir.rglob("*.[0-9][0-9]o"))
        + list(rinex_dir.rglob("*.rnx"))
        + list(rinex_dir.rglob("*.RNX"))
    )
    if not files:
        pytest.skip(f"No RINEX files in {rinex_dir}")
    return files[0]


@pytest.fixture
def demo_rosalia_canopy(demo_rosalia_dir: Path) -> Path:
    """Demo Rosalia canopy RINEX file (first available)."""
    rinex_dir = demo_rosalia_dir / "02_canopy/01_GNSS/01_raw"
    if not rinex_dir.exists():
        pytest.skip(f"RINEX directory not found: {rinex_dir}")
    # Find any RINEX file in any subdirectory
    files = (
        list(rinex_dir.rglob("*.[0-9][0-9]o"))
        + list(rinex_dir.rglob("*.rnx"))
        + list(rinex_dir.rglob("*.RNX"))
    )
    if not files:
        pytest.skip(f"No RINEX files in {rinex_dir}")
    return files[0]


@pytest.fixture
def demo_rosalia_reference_day(demo_rosalia_dir: Path) -> Path:
    """Demo Rosalia reference directory for day 001 (2025-001)."""
    day_dir = demo_rosalia_dir / "01_reference/01_GNSS/01_raw/25001"
    if not day_dir.exists():
        pytest.skip(f"Day directory not found: {day_dir}")
    return day_dir


@pytest.fixture
def demo_rosalia_canopy_day(demo_rosalia_dir: Path) -> Path:
    """Demo Rosalia canopy directory for day 001 (2025-001)."""
    day_dir = demo_rosalia_dir / "02_canopy/01_GNSS/01_raw/25001"
    if not day_dir.exists():
        pytest.skip(f"Day directory not found: {day_dir}")
    return day_dir


# Mark for tests that require demo data
requires_demo = pytest.mark.skipif(
    not DEMO_ROOT.exists(), reason="Demo submodule not initialized"
)
