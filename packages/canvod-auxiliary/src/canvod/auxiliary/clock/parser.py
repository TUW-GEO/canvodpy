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
        elif "OF SOLN SATS" in line:
            _ = int(line[4:6])
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
    # First pass: collect all epochs and satellites
    epochs = []
    satellites = set()
    clock_records = []
    current_epoch = None

    for line in file_handle:
        if line.startswith("AS"):
            parts = line.split()

            # Parse epoch
            epoch = datetime.datetime(
                year=int(parts[2]),
                month=int(parts[3]),
                day=int(parts[4]),
                hour=int(parts[5]),
                minute=int(parts[6]),
                second=int(float(parts[7])),
            )

            # Store unique epochs and satellites
            if epoch != current_epoch:
                current_epoch = epoch
                epochs.append(epoch)

            sv_code = parts[1]
            satellites.add(sv_code)

            # Store complete record
            clock_offset = float(parts[9])  # seconds (RINEX clock 3.04, Table A16)
            clock_records.append((epoch, sv_code, clock_offset))

    # Create lookup dictionaries for efficient indexing
    epoch_idx = {epoch: i for i, epoch in enumerate(epochs)}
    sv_list = sorted(satellites)
    sv_idx = {sv: i for i, sv in enumerate(sv_list)}

    # Pre-allocate array with NaN
    shape = (len(epochs), len(sv_list))
    clock_offsets = np.full(shape, np.nan)

    # Fill array using collected records
    for epoch, sv, offset in clock_records:
        i = epoch_idx[epoch]
        j = sv_idx[sv]
        clock_offsets[i, j] = offset

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
