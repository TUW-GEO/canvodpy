"""Site folders on the Rosalia test data, with a synthetic second day.

The second day (2025002) is the test day's files with every date moved one
day on (the epochs, the header and the file name), so the data are the
same and only the time differs. The orbit and clock files of both days are
in the test data.
"""

from __future__ import annotations

import re
from pathlib import Path

TEST_DATA = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "canvod-readers"
    / "tests"
    / "test_data"
    / "valid"
)
ROSALIA = TEST_DATA / "rinex_v3_04" / "01_Rosalia"
AUX = TEST_DATA / "aux_data"
RECEIVERS = {
    "reference_01": "01_reference/01_GNSS/01_raw",
    "canopy_01": "02_canopy/01_GNSS/01_raw",
}
# Two hours of each day: enough for runs to meet, short enough for CI.
FILES_PER_DAY = 8
EPOCHS_PER_FILE = 180  # 15 min at 5 s


def next_day(text: str) -> str:
    """Move every date of a RINEX 3 observation file from 2025-01-01 to 01-02."""
    # Epoch records (RINEX 3.04, section 5.2.3) and the TIME OF FIRST/LAST
    # OBS header records (Table A2).
    text = re.sub(r"^> 2025 01 01 ", "> 2025 01 02 ", text, flags=re.MULTILINE)
    return re.sub(
        r"^(  2025     1)     1(.*TIME OF (?:FIRST|LAST) OBS)",
        r"\1     2\2",
        text,
        flags=re.MULTILINE,
    )


def day_files(day: str, receiver_dir: str, synthetic: Path) -> list[Path]:
    """The first ``FILES_PER_DAY`` files of a receiver on ``day``.

    Files of 2025002 are written to ``synthetic`` the first time.
    """
    source = ROSALIA / receiver_dir / "25001"
    files = sorted(f for f in source.iterdir() if f.name.endswith(".rnx"))
    files = files[:FILES_PER_DAY]
    if day == "2025001":
        return files
    target = synthetic / receiver_dir / "25002"
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in files:
        out = target / f.name.replace("_2025001", "_2025002")
        if not out.exists():
            out.write_text(next_day(f.read_text()))
        moved.append(out)
    return moved


def site_data(root: Path, files: dict[str, dict[str, slice]], synthetic: Path) -> Path:
    """A site folder with the files a run holds: ``{day: {receiver: slice}}``."""
    for day, receivers in files.items():
        for receiver, part in receivers.items():
            receiver_dir = RECEIVERS[receiver]
            target = root / receiver_dir / day[2:]
            target.mkdir(parents=True, exist_ok=True)
            for f in day_files(day, receiver_dir, synthetic)[part]:
                (target / f.name).symlink_to(f)
    return root


def link_aux(folder: Path) -> None:
    """Link the orbit and clock files of both days into ``folder``."""
    for aux, pattern in (("01_SP3", "*ORB.SP3"), ("02_CLK", "*CLK.CLK")):
        (folder / aux).mkdir(parents=True, exist_ok=True)
        for f in AUX.joinpath(aux).glob(pattern):
            (folder / aux / f.name).symlink_to(f)
