"""Tests for canvod.preflight.mapping."""

import pytest

from canvod.preflight.config_models import (
    DirectoryLayout,
    ReceiverNamingConfig,
    SiteNamingConfig,
)
from canvod.preflight.convention import FileType, ReceiverType
from canvod.preflight.mapping import (
    FilenameMapper,
    VirtualFile,
    _detect_file_type,
)
from canvod.utils import testing

# -- Fixtures -----------------------------------------------------------------


# Tests of the deprecated mapping and validation API, see test_deprecations.py.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


@pytest.fixture
def site_naming():
    return SiteNamingConfig(site_id=testing.SITE_ID, agency=testing.AGENCY)


@pytest.fixture
def rx_naming():
    return ReceiverNamingConfig(
        receiver_number=1,
        source_pattern="auto",
        directory_layout=DirectoryLayout.YYDDD_SUBDIRS,
    )


@pytest.fixture
def yyddd_tree(tmp_path, site_naming, rx_naming):
    """Create a YYDDD directory tree with sample files."""
    base = tmp_path / "01_reference"
    # DOY 001 of 2025
    d1 = base / "25001"
    d1.mkdir(parents=True)
    (d1 / "rosl001a.25o").write_bytes(b"data")
    (d1 / "rref001a00.25_").write_bytes(b"data")

    # DOY 002 of 2025
    d2 = base / "25002"
    d2.mkdir(parents=True)
    (d2 / "rosl002a.25o").write_bytes(b"data")

    return base


@pytest.fixture
def yyyyddd_tree(tmp_path):
    """Create a YYYYDDD directory tree with sample files."""
    base = tmp_path / "01_reference"
    d1 = base / "2025001"
    d1.mkdir(parents=True)
    (d1 / "FANA00INK_R_20250010000_01D_05S_MO.rnx").write_bytes(b"data")
    return base


@pytest.fixture
def flat_tree(tmp_path):
    """Create a flat directory with sample files."""
    base = tmp_path / "01_reference"
    base.mkdir(parents=True)
    (base / "rosl001a.25o").write_bytes(b"data")
    (base / "rosl002a.25o").write_bytes(b"data")
    (base / "README.txt").write_bytes(b"ignore me")
    return base


# -- _detect_file_type --------------------------------------------------------


class TestDetectFileType:
    def test_rnx(self, tmp_path):
        p = tmp_path / "file.rnx"
        p.touch()
        ft, comp = _detect_file_type(p)
        assert ft == FileType.RNX
        assert comp is None

    def test_rnx_gz(self, tmp_path):
        p = tmp_path / "file.rnx.gz"
        p.touch()
        ft, comp = _detect_file_type(p)
        assert ft == FileType.RNX
        assert comp == "gz"

    def test_sbf(self, tmp_path):
        p = tmp_path / "file.sbf"
        p.touch()
        ft, comp = _detect_file_type(p)
        assert ft == FileType.SBF
        assert comp is None

    def test_rinex_v2_obs(self, tmp_path):
        p = tmp_path / "rosl001a.25o"
        p.touch()
        ft, comp = _detect_file_type(p)
        assert ft == FileType.RNX
        assert comp is None

    def test_septentrio_sbf_ext(self, tmp_path):
        p = tmp_path / "rref001a00.25_"
        p.touch()
        ft, comp = _detect_file_type(p)
        assert ft == FileType.SBF
        assert comp is None

    def test_ubx(self, tmp_path):
        p = tmp_path / "file.ubx"
        p.touch()
        ft, comp = _detect_file_type(p)
        assert ft == FileType.UBX
        assert comp is None

    def test_unknown_raises(self, tmp_path):
        p = tmp_path / "file.txt"
        p.touch()
        with pytest.raises(ValueError, match="Cannot detect"):
            _detect_file_type(p)


# -- VirtualFile --------------------------------------------------------------


class TestVirtualFile:
    def test_canonical_str(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "test.rnx"
        p.write_bytes(b"data")

        from canvod.preflight.convention import CanVODFilename

        cn = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        vf = VirtualFile(physical_path=p, conventional_name=cn)
        assert vf.canonical_str == "FANR01INK_R_20250010000_01D_05S_AA.rnx"

    def test_open(self, tmp_path):
        p = tmp_path / "test.rnx"
        p.write_bytes(b"hello")

        from canvod.preflight.convention import CanVODFilename

        cn = CanVODFilename(
            site=testing.SITE_ID,
            receiver_type=ReceiverType.REFERENCE,
            receiver_number=1,
            agency=testing.AGENCY,
            year=2025,
            doy=1,
        )
        vf = VirtualFile(physical_path=p, conventional_name=cn)
        with vf.open() as f:
            assert f.read() == b"hello"


# -- FilenameMapper -----------------------------------------------------------


class TestFilenameMapperYYDDD:
    def test_discover_all(self, yyddd_tree, site_naming, rx_naming):
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=yyddd_tree,
        )
        vfs = mapper.discover_all()
        assert len(vfs) == 3
        names = [vf.conventional_name.name for vf in vfs]
        # All should have the made-up site, R receiver type and agency
        for vf in vfs:
            assert vf.conventional_name.site == testing.SITE_ID
            assert vf.conventional_name.receiver_type == ReceiverType.REFERENCE
            assert vf.conventional_name.agency == testing.AGENCY

    def test_discover_for_date(self, yyddd_tree, site_naming, rx_naming):
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=yyddd_tree,
        )
        vfs = mapper.discover_for_date(2025, 1)
        assert len(vfs) == 2  # rosl001a.25o and rref001a00.25_

    def test_discover_for_date_empty(self, yyddd_tree, site_naming, rx_naming):
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=yyddd_tree,
        )
        vfs = mapper.discover_for_date(2025, 99)
        assert len(vfs) == 0


class TestFilenameMapperYYYYDDD:
    def test_discover_all(self, yyyyddd_tree, site_naming):
        rx = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout=DirectoryLayout.YYYYDDD_SUBDIRS,
        )
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx,
            receiver_type="canopy",
            receiver_base_dir=yyyyddd_tree,
        )
        vfs = mapper.discover_all()
        assert len(vfs) == 1
        assert vfs[0].conventional_name.receiver_type == ReceiverType.ACTIVE

    def test_discover_for_date(self, yyyyddd_tree, site_naming):
        rx = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout=DirectoryLayout.YYYYDDD_SUBDIRS,
        )
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx,
            receiver_type="canopy",
            receiver_base_dir=yyyyddd_tree,
        )
        vfs = mapper.discover_for_date(2025, 1)
        assert len(vfs) == 1


class TestFilenameMapperFlat:
    def test_discover_all(self, flat_tree, site_naming):
        rx = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout=DirectoryLayout.FLAT,
        )
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx,
            receiver_type="reference",
            receiver_base_dir=flat_tree,
        )
        vfs = mapper.discover_all()
        # README.txt won't match any pattern
        assert len(vfs) == 2

    def test_discover_for_date(self, flat_tree, site_naming):
        rx = ReceiverNamingConfig(
            receiver_number=1,
            source_pattern="auto",
            directory_layout=DirectoryLayout.FLAT,
        )
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx,
            receiver_type="reference",
            receiver_base_dir=flat_tree,
        )
        vfs = mapper.discover_for_date(2025, 1)
        assert len(vfs) == 1


class TestMapSingleFile:
    def test_rinex_v2(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "rosl001a.25o"
        p.write_bytes(b"data")

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        vf = mapper.map_single_file(p)
        cn = vf.conventional_name
        assert cn.site == testing.SITE_ID
        assert cn.year == 2025
        assert cn.doy == 1
        assert cn.hour == 0
        assert cn.file_type == FileType.RNX

    def test_septentrio_sbf(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "rref001a00.25_"
        p.write_bytes(b"data")

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        vf = mapper.map_single_file(p)
        cn = vf.conventional_name
        assert cn.file_type == FileType.SBF
        assert cn.year == 2025
        assert cn.doy == 1

    def test_canvod_filename(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "FANR01INK_R_20250010000_01D_05S_AA.rnx"
        p.write_bytes(b"data")

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        vf = mapper.map_single_file(p)
        # Should round-trip perfectly
        assert vf.canonical_str == "FANR01INK_R_20250010000_01D_05S_AA.rnx"

    def test_unmatched_raises(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "random.txt"
        p.write_bytes(b"data")

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="No pattern matched"):
            mapper.map_single_file(p)

    def test_with_date_override(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "rosl001a.25o"
        p.write_bytes(b"data")

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path,
        )
        vf = mapper.map_single_file(p, year=2025, doy=1)
        assert vf.conventional_name.year == 2025
        assert vf.conventional_name.doy == 1

    def test_canopy_receiver_type(self, tmp_path, site_naming, rx_naming):
        p = tmp_path / "rosl001a.25o"
        p.write_bytes(b"data")

        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="canopy",
            receiver_base_dir=tmp_path,
        )
        vf = mapper.map_single_file(p)
        assert vf.conventional_name.receiver_type == ReceiverType.ACTIVE


class TestFilenameMapperNonexistentDir:
    def test_discover_all_missing_dir(self, tmp_path, site_naming, rx_naming):
        mapper = FilenameMapper(
            site_naming=site_naming,
            receiver_naming=rx_naming,
            receiver_type="reference",
            receiver_base_dir=tmp_path / "nonexistent",
        )
        vfs = mapper.discover_all()
        assert vfs == []
