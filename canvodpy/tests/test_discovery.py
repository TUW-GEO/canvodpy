"""Tests for the file discovery shared by ``canvodpy run`` and its dry run."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from canvodpy.orchestrator.discovery import (
    DiscoveredFile,
    DiscoveryError,
    ReceiverDay,
    canonical_name_for,
    check_receivers,
    clear_discovery_cache,
    detect_reader_format,
    discover_files,
    is_compressed,
    receiver_days,
    recipe_file,
    scan_directory,
    unprocessed_files,
)

from canvod.utils import testing

CANONICAL = "FANA01INK_R_20250010000_15M_05S_AA.rnx"
DAY = "2025001"


@pytest.fixture(autouse=True)
def _fresh_index():
    """Each test scans its directories anew."""
    clear_discovery_cache()
    yield
    clear_discovery_cache()


def _touch(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("")


def _names(directory: Path, reader_format: str | None = None, day: str = DAY):
    found = discover_files(ReceiverDay("rx", directory, day), reader_format)
    return [f.path.name for f in found]


def test_canonical_name_for() -> None:
    assert canonical_name_for(Path("/data") / CANONICAL) == CANONICAL
    assert canonical_name_for("rref001a00.25o") == ""


def test_convention_discovery_by_reader_format(tmp_path: Path) -> None:
    _touch(tmp_path, CANONICAL, "FANA01INK_R_20250010000_15M_05S_AA.sbf", "x.txt")
    assert _names(tmp_path, "rinex3") == [CANONICAL]
    assert _names(tmp_path, "sbf") == ["FANA01INK_R_20250010000_15M_05S_AA.sbf"]
    assert len(_names(tmp_path, "auto")) == 2
    found = discover_files(ReceiverDay("rx", tmp_path, DAY), "rinex3")
    assert found[0].canonical_name == CANONICAL


def test_non_canonical_files_are_ignored(tmp_path: Path) -> None:
    """Without a recipe only names following the convention are processed."""
    _touch(
        tmp_path,
        CANONICAL,
        "rref001a00.25o",  # RINEX v2 short name
        "FANA00INK_R_20250010000_01D_30S_MO.rnx",  # RINEX v3 long name
        "rosa001a.rnx",
        "FANA01INK_R_20250010045_15M_05S_AA.RNX",  # upper-case extension
        "FANA01INK_R_20250010015_15M_05S_AA.rnx.gz",  # compressed
        "FANA01INK_R_20250010030_15M_05S_AA.ubx",  # no reader
    )
    assert _names(tmp_path) == [CANONICAL]


def test_installed_filemap_does_not_widen_discovery(tmp_path: Path) -> None:
    """Having canvod-filemap installed must not change non-recipe discovery."""
    _touch(tmp_path, CANONICAL, "rref001a00.25o", "rosa001a.rnx")
    fake_patterns = SimpleNamespace(
        BUILTIN_PATTERNS={"any": SimpleNamespace(file_globs=("*",))},
        auto_match_order=lambda: ("any",),
    )
    with mock.patch.dict("sys.modules", {"canvod.filemap.patterns": fake_patterns}):
        assert _names(tmp_path) == [CANONICAL]


def _rinex(path: Path, version: str) -> DiscoveredFile:
    """A RINEX file whose header gives ``version``."""
    path.write_text(
        f"{version:>9}           OBSERVATION DATA    M                   "
        "RINEX VERSION / TYPE\n"
        "G    1 C1C                                                  "
        "SYS / # / OBS TYPES\n"
        "                                                            "
        "END OF HEADER\n"
    )
    return DiscoveredFile(path, CANONICAL)


def test_detect_reader_format_by_file_type() -> None:
    sbf = DiscoveredFile(Path("b"), CANONICAL.replace(".rnx", ".sbf"))
    nmea = DiscoveredFile(Path("c"), CANONICAL.replace(".rnx", ".nmea"))
    assert detect_reader_format([sbf]) == "sbf"
    assert detect_reader_format([nmea]) == "nmea"


def test_detect_reader_format_rinex_version_from_header(tmp_path: Path) -> None:
    assert detect_reader_format([_rinex(tmp_path / "a", "3.04")]) == "rinex3"
    assert detect_reader_format([_rinex(tmp_path / "b", "2.11")]) == "rinex2"


def test_detect_reader_format_refuses_mixed_files(tmp_path: Path) -> None:
    """A day whose files need different readers is an error, never a guess."""
    rnx3 = _rinex(tmp_path / "a", "3.04")
    rnx2 = _rinex(tmp_path / "b", "2.11")
    sbf = DiscoveredFile(Path("c"), CANONICAL.replace(".rnx", ".sbf"))
    with pytest.raises(DiscoveryError, match="different readers"):
        detect_reader_format([rnx3, sbf])
    with pytest.raises(DiscoveryError, match="different readers"):
        detect_reader_format([rnx3, rnx2])
    with pytest.raises(DiscoveryError, match="No files"):
        detect_reader_format([])
    empty = tmp_path / "empty"
    empty.write_text("")
    with pytest.raises(DiscoveryError, match="Set reader_format"):
        detect_reader_format([DiscoveredFile(empty, CANONICAL)])


def test_rinex2_and_nmea_files_are_discovered(tmp_path: Path) -> None:
    nmea = CANONICAL.replace(".rnx", ".nmea")
    sbf = CANONICAL.replace(".rnx", ".sbf")
    _touch(tmp_path, CANONICAL, nmea, sbf)
    assert _names(tmp_path, "rinex2") == [CANONICAL]
    assert _names(tmp_path, "nmea") == [nmea]
    assert len(_names(tmp_path, "auto")) == 3


def test_missing_directory_yields_nothing(tmp_path: Path) -> None:
    assert _names(tmp_path / "absent") == []
    assert receiver_days("rx", tmp_path / "absent") == []


# -- Folder layouts ------------------------------------------------------------

DAY1 = "FANA01INK_R_20250010000_15M_05S_AA.rnx"
DAY1_LATE = "FANA01INK_R_20250012345_15M_05S_AA.rnx"
DAY2 = "FANA01INK_R_20250020000_15M_05S_AA.rnx"


@pytest.mark.parametrize(
    "layout",
    [
        {"": [DAY1, DAY1_LATE, DAY2]},  # flat
        {"25001": [DAY1, DAY1_LATE], "25002": [DAY2]},  # YYDDD folders
        {"2025001": [DAY1, DAY1_LATE], "2025002": [DAY2]},  # YYYYDDD folders
        {"2025/001": [DAY1], "2025/001/late": [DAY1_LATE], "2025/002": [DAY2]},
        {"25001": [DAY1, DAY2], "misc": [DAY1_LATE]},  # misfiled day
    ],
    ids=["flat", "yyddd", "yyyyddd", "nested", "misfiled"],
)
def test_day_comes_from_filename_not_folder(
    tmp_path: Path, layout: dict[str, list[str]]
) -> None:
    for folder, names in layout.items():
        _touch(tmp_path / folder, *names)
    days = receiver_days("rx", tmp_path)
    assert [d.yyyydoy for d in days] == ["2025001", "2025002"]
    assert _names(tmp_path, day="2025001") == [DAY1, DAY1_LATE]
    assert _names(tmp_path, day="2025002") == [DAY2]


def test_hidden_folders_and_symlinks_are_skipped(tmp_path: Path) -> None:
    _touch(tmp_path / "data", DAY1)
    _touch(tmp_path / ".snapshot", DAY1_LATE)
    _touch(tmp_path / "elsewhere", DAY2)
    (tmp_path / "data" / "link").symlink_to(tmp_path / "elsewhere")
    assert [d.yyyydoy for d in receiver_days("rx", tmp_path / "data")] == [DAY]


def test_same_canonical_name_twice_is_an_error(tmp_path: Path) -> None:
    _touch(tmp_path / "25001", DAY1)
    _touch(tmp_path / "backup", DAY1)
    with pytest.raises(DiscoveryError, match="same canonical name"):
        receiver_days("rx", tmp_path)


def test_several_receivers_in_one_folder_is_an_error(tmp_path: Path) -> None:
    _touch(tmp_path, DAY1, "FANR01INK_R_20250010000_15M_05S_AA.rnx")
    with pytest.raises(DiscoveryError, match="its own directory"):
        receiver_days("rx", tmp_path)


def test_index_is_rescanned_after_clearing(tmp_path: Path) -> None:
    _touch(tmp_path, DAY1)
    assert len(receiver_days("rx", tmp_path)) == 1
    _touch(tmp_path, DAY2)
    assert len(receiver_days("rx", tmp_path)) == 1  # cached for the run
    clear_discovery_cache()
    assert len(receiver_days("rx", tmp_path)) == 2


def test_recipes_are_read_from_the_site_folder_of_the_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("canvod.filemap.recipe_files")
    _touch(tmp_path / "recipes" / "fangorn", "ref.yaml")
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    assert (
        recipe_file("fangorn", "ref") == tmp_path / "recipes" / "fangorn" / "ref.yaml"
    )
    assert recipe_file("fangorn", None) is None
    # No fallback to the checkout's config/recipes/
    with pytest.raises(DiscoveryError, match="just naming-init fangorn _template"):
        recipe_file("fangorn", "_template")


def test_recipe_outside_its_site_folder_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("canvod.filemap.recipe_files")
    _touch(tmp_path / "recipes", "ref.yaml")
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    with pytest.raises(DiscoveryError, match=r"Move .* to .*fangorn"):
        recipe_file("fangorn", "ref")


def test_recipe_drives_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A receiver recipe selects non-canonical files and maps their names."""
    pytest.importorskip("canvod.filemap.recipe_files")
    (tmp_path / "recipes" / "fangorn").mkdir(parents=True)
    (tmp_path / "recipes" / "fangorn" / "ros_ref.yaml").write_text(
        "name: ros_ref\n"
        "site: FAN\n"
        "agency: INK\n"
        "receiver_number: 1\n"
        "receiver_type: reference\n"
        "sampling: '05S'\n"
        "period: '15M'\n"
        "file_type: rnx\n"
        "glob: '*.??o'\n"
        "fields:\n"
        "  - skip: 4\n"
        "  - doy: 3\n"
        "  - hour_letter: 1\n"
        "  - minute: 2\n"
        "  - skip: 1\n"
        "  - yy: 2\n"
        "  - skip: 1\n"
    )
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    data_dir = tmp_path / "01_reference"
    _touch(data_dir / "25001", "rref001a15.25o", CANONICAL)
    _touch(data_dir, "rref002a00.25o")  # a different day, outside day folders

    recipe = recipe_file("fangorn", "ros_ref")
    days = receiver_days("reference_01", data_dir, recipe=recipe)
    assert [d.yyyydoy for d in days] == ["2025001", "2025002"]
    found = discover_files(days[0], "rinex3")

    assert [f.path.name for f in found] == ["rref001a15.25o"]
    assert found[0].canonical_name == "FANR01INK_R_20250010015_15M_05S_AA.rnx"


def _recipes(**recipes: SimpleNamespace):
    """Patch recipe loading to return the given recipes by name."""
    return (
        mock.patch(
            "canvodpy.orchestrator.discovery.recipe_file",
            side_effect=lambda site, name: name,
        ),
        mock.patch(
            "canvodpy.orchestrator.discovery._load_recipe",
            side_effect=lambda name: recipes[name],
        ),
    )


def _recipe(receiver_type: str, number: int) -> SimpleNamespace:
    return SimpleNamespace(
        site=testing.SITE_ID,
        agency=testing.AGENCY,
        receiver_type=receiver_type,
        receiver_number=number,
    )


def test_recipe_receivers_with_distinct_identities_pass(tmp_path: Path) -> None:
    receivers = {
        "reference_01": {"type": "reference", "directory": "r", "recipe": "ref"},
        "canopy_01": {"type": "canopy", "directory": "c1", "recipe": "can1"},
        "canopy_02": {"type": "canopy", "directory": "c2", "recipe": "can2"},
        "canopy_03": {"type": "canopy", "directory": "c3", "recipe": None},
    }
    a, b = _recipes(
        ref=_recipe("reference", 1),
        can1=_recipe("canopy", 1),
        can2=_recipe("canopy", 2),
    )
    with a, b, mock.patch.dict("sys.modules", {"canvod.filemap": SimpleNamespace()}):
        check_receivers(receivers, tmp_path, "fangorn")


def test_shared_recipe_identity_is_rejected(tmp_path: Path) -> None:
    """Two canopies sharing one recipe would both be named FANA01INK."""
    receivers = {
        "canopy_01": {"type": "canopy", "directory": "c1", "recipe": "can"},
        "canopy_02": {"type": "canopy", "directory": "c2", "recipe": "can"},
    }
    a, b = _recipes(can=_recipe("canopy", 1))
    with (
        a,
        b,
        mock.patch.dict("sys.modules", {"canvod.filemap": SimpleNamespace()}),
        pytest.raises(DiscoveryError, match="FANA01INK"),
    ):
        check_receivers(receivers, tmp_path, "fangorn")


def test_recipe_receiver_type_must_match(tmp_path: Path) -> None:
    receivers = {"canopy_01": {"type": "canopy", "directory": "c", "recipe": "ref"}}
    a, b = _recipes(ref=_recipe("reference", 1))
    with (
        a,
        b,
        mock.patch.dict("sys.modules", {"canvod.filemap": SimpleNamespace()}),
        pytest.raises(DiscoveryError, match="FANR01INK, the identity of a reference"),
    ):
        check_receivers(receivers, tmp_path, "fangorn")


def test_recipe_without_filemap_is_an_error(tmp_path: Path) -> None:
    receivers = {
        "canopy_01": {"type": "canopy", "directory": "c", "recipe": "can"},
        "reference_01": {"type": "reference", "directory": "r"},
    }
    with (
        mock.patch.dict("sys.modules", {"canvod.filemap": None}),
        pytest.raises(DiscoveryError, match="uv sync --group filemap") as exc_info,
    ):
        check_receivers(receivers, tmp_path, "fangorn")
    assert "canopy_01" in str(exc_info.value)
    assert "reference_01" not in str(exc_info.value)


def test_missing_recipe_file_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("canvod.filemap.recipe_files")
    monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path))
    receivers = {"canopy_01": {"type": "canopy", "directory": "c", "recipe": "nope"}}
    with pytest.raises(DiscoveryError, match="Recipe file not found for 'nope'"):
        check_receivers(receivers, tmp_path, "fangorn")


def test_canonical_receivers_with_the_same_identity_are_rejected(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "c1", DAY1)
    _touch(tmp_path / "c2", DAY2)
    receivers = {
        "canopy_01": {"type": "canopy", "directory": "c1"},
        "canopy_02": {"type": "canopy", "directory": "c2"},
    }
    with pytest.raises(DiscoveryError, match="'canopy_01' and 'canopy_02'"):
        check_receivers(receivers, tmp_path, "fangorn")


def test_canonical_receiver_role_must_match_type(tmp_path: Path) -> None:
    _touch(tmp_path / "r", DAY1)  # FANA01INK: a canopy identity
    receivers = {"reference_01": {"type": "reference", "directory": "r"}}
    with pytest.raises(DiscoveryError, match="configured as 'reference'"):
        check_receivers(receivers, tmp_path, "fangorn")


def test_receivers_without_files_pass(tmp_path: Path) -> None:
    receivers = {
        "canopy_01": {"type": "canopy", "directory": "absent"},
        "canopy_02": {"type": "canopy", "directory": "absent_too"},
    }
    check_receivers(receivers, tmp_path, "fangorn")


def test_scan_reports_unrecognized_files(tmp_path: Path) -> None:
    _touch(tmp_path, DAY1, "notes.txt", DAY2 + ".gz")
    scan = scan_directory(tmp_path)
    assert scan.identity == "FANA01INK"
    assert {p.name for p in scan.unrecognized} == {"notes.txt"}
    assert [p.name for p in scan.compressed] == [DAY2 + ".gz"]
    assert list(scan.days) == ["2025001"]


@pytest.mark.parametrize(
    ("name", "compressed"),
    [
        (DAY1 + ".gz", True),
        ("rosa0010.25o.Z", True),
        ("rosa0010.25o.zip", True),
        ("FANA00INK_R_20250010000_01D_30S_MO.crx", True),
        ("FANA00INK_R_20250010000_01D_30S_MO.crx.gz", True),
        ("rosa0010.25d", True),
        ("rosa0010.25D", True),
        (DAY1, False),
        ("rosa0010.25o", False),
        ("FANA01INK_R_20250010000_15M_05S_AA.sbf", False),
        ("notes.txt", False),
    ],
)
def test_is_compressed(name: str, compressed: bool) -> None:
    assert is_compressed(Path(name)) is compressed


def test_recipe_never_sees_compressed_files(tmp_path: Path) -> None:
    """A recipe whose glob also matches compressed files does not get them."""
    seen: list[str] = []

    def matches(name: str) -> bool:
        seen.append(name)
        return False

    recipe = SimpleNamespace(glob="*", matches=matches)
    _touch(tmp_path, "rref001a00.25o", "rref001a15.25o.gz", "rref001a30.25d")
    with mock.patch(
        "canvodpy.orchestrator.discovery._load_recipe", return_value=recipe
    ):
        scan = scan_directory(tmp_path, Path("ref.yaml"))
        skipped = unprocessed_files(tmp_path, recipe=Path("ref.yaml"))
    assert seen == ["rref001a00.25o"]
    assert [p.name for p in scan.compressed] == ["rref001a15.25o.gz", "rref001a30.25d"]
    assert [p.name for p in skipped] == [
        "rref001a15.25o.gz",
        "rref001a30.25d",
        "rref001a00.25o",
    ]


@pytest.mark.parametrize(
    "extra",
    [
        "FANA01INK_R_20250010000_01D_05S_AA.rnx",  # daily next to sub-daily
        "FANA01INK_R_20250010000_15M_01S_AA.rnx",  # same span, other sampling
        "FANA01INK_R_20250010010_15M_05S_AA.rnx",  # partial overlap
    ],
    ids=["daily", "equal", "partial"],
)
def test_overlapping_files_are_an_error(tmp_path: Path, extra: str) -> None:
    _touch(tmp_path / "25001", DAY1, "FANA01INK_R_20250010015_15M_05S_AA.rnx")
    _touch(tmp_path / "other", extra)
    with pytest.raises(DiscoveryError, match=r"overlaps .*\n.*not both"):
        receiver_days("rx", tmp_path)


def test_sbf_next_to_its_rinex_is_no_overlap(tmp_path: Path) -> None:
    _touch(tmp_path, DAY1, DAY1.replace(".rnx", ".sbf"))
    assert _names(tmp_path, "sbf") == [DAY1.replace(".rnx", ".sbf")]
