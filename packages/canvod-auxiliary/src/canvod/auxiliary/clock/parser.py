"""CLK format parser.

This module handles parsing of RINEX CLK (clock) files containing satellite
clock offset data. It implements a two-pass reading strategy to handle files
where satellites may appear or disappear during the time period.

Key Features:
    - Two-pass reading for complete satellite/epoch coverage
    - Handles missing satellites in header
    - Efficient numpy array allocation
    - Robust datetime parsing
"""

import datetime
from pathlib import Path
from typing import TextIO

import numpy as np


def parse_clk_header(file_handle: TextIO) -> set[str]:
    """Parse CLK file header to extract satellite list.

    Parameters
    ----------
    file_handle : TextIO
        Open file object positioned at start.

    Returns
    -------
    set[str]
        Satellite identifiers (e.g., "G01", "R01").

    Raises
    ------
    ValueError
        If header format is invalid, or if the time system (``TIME SYSTEM
        ID``; GPS if absent) is not GPS time.
    """
    satellites = set()

    for line in file_handle:
        if "TIME SYSTEM ID" in line:
            time_system = line[3:6]
            if time_system != "GPS":
                msg = (
                    f"CLK time system is {time_system!r}, but canVODpy needs "
                    "clocks in GPS time ('GPS'), the time scale of the stored "
                    "observation epochs. Use a product in GPS time."
                )
                raise ValueError(msg)
        elif "PRN LIST" in line:
            # Parse PRN list line(s)
            parts = line.split()[2:]  # Skip 'PRN' and 'LIST'
            for prn in parts:
                if len(prn) == 3:  # Valid PRN format (e.g., G01)
                    satellites.add(prn)
        elif "END OF HEADER" in line:
            break

    return satellites


def parse_clk_data(
    file_handle: TextIO,
) -> tuple[list[datetime.datetime], list[str], np.ndarray]:
    """Parse CLK data records using two-pass strategy.

    Two-Pass Strategy:
        Pass 1: Collect all unique epochs and satellites
        Pass 2: Fill data arrays with clock offsets

    This ensures we capture all satellites, even if they're not in the header,
    and handles satellites appearing/disappearing during the time period.

    Parameters
    ----------
    file_handle : TextIO
        Open file object positioned after header.

    Returns
    -------
    tuple[list[datetime.datetime], list[str], np.ndarray]
        (epochs, satellites, clock_offsets) where:
        - epochs: list of datetime objects
        - satellites: sorted list of satellite codes
        - clock_offsets: 2D array (epochs × satellites) in seconds
    """
    # First pass: collect the epochs, and per record its epoch row, satellite
    # and offset. Records come grouped by epoch, so an epoch is parsed once.
    epochs: list[datetime.datetime] = []
    rows: list[int] = []
    sv_codes: list[str] = []
    offsets: list[float] = []
    current_fields = None

    for line in file_handle:
        if line.startswith("AS"):
            parts = line.split(None, 10)

            epoch_fields = parts[2:8]
            if epoch_fields != current_fields:
                current_fields = epoch_fields
                epoch = datetime.datetime(
                    year=int(parts[2]),
                    month=int(parts[3]),
                    day=int(parts[4]),
                    hour=int(parts[5]),
                    minute=int(parts[6]),
                    second=int(float(parts[7])),
                )
                if not epochs or epoch != epochs[-1]:
                    epochs.append(epoch)
            rows.append(len(epochs) - 1)
            sv_codes.append(parts[1])

            # seconds (RINEX clock 3.04, Table A16); some centers (IAC) write
            # Fortran exponents, 0.612D-03
            value = parts[9]
            if "D" in value or "d" in value:
                value = value.upper().replace("D", "E")
            offsets.append(float(value))

    # Second pass: fill the array, all records at once
    sv_list = sorted(set(sv_codes))
    sv_idx = {sv: i for i, sv in enumerate(sv_list)}
    clock_offsets = np.full((len(epochs), len(sv_list)), np.nan)
    columns = np.fromiter((sv_idx[sv] for sv in sv_codes), np.intp, len(sv_codes))
    clock_offsets[np.asarray(rows, dtype=np.intp), columns] = offsets

    return epochs, sv_list, clock_offsets


def parse_clk_file(
    filepath: Path,
) -> tuple[list[datetime.datetime], list[str], np.ndarray]:
    """Parse complete CLK file.

    Parameters
    ----------
    filepath : Path
        Path to CLK file.

    Returns
    -------
    tuple[list[datetime.datetime], list[str], np.ndarray]
        (epochs, satellites, clock_offsets).
    """
    with filepath.open() as f:
        # Parse header (checks the time system; satellites come from the data)
        try:
            _ = parse_clk_header(f)
        except ValueError as e:
            raise ValueError(f"{filepath.name}: {e}") from e

        # Parse data
        epochs, satellites, clock_offsets = parse_clk_data(f)

    return epochs, satellites, clock_offsets
