"""Build the demo data zips for Hugging Face from ``canvodpy.demo.ARCHIVES``.

Each zip holds the files its ``members`` patterns match in the test data
folder, at the same relative paths. The zips are deterministic (sorted
members, fixed timestamps), so a rebuild from the same test data gives
the same sha256. Prints name, size and sha256 of each zip; copy the sha256 into
``ARCHIVES``.

Usage: ``just demo-archives [OUT] [TEST_DATA]``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

from canvodpy.demo import ARCHIVES

DEFAULT_TEST_DATA = Path("packages/canvod-readers/tests/test_data/valid")
FIXED_TIME = (2025, 1, 1, 0, 0, 0)


def build(out: Path, test_data: Path) -> None:
    """Write every archive of ``ARCHIVES`` to ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    for archive in ARCHIVES:
        files = sorted(
            {
                path
                for pattern in archive.members
                for path in test_data.glob(pattern)
                if path.is_file()
            }
        )
        if not files:
            sys.exit(f"{archive.name}: no file matches {archive.members}")
        target = out / archive.name
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                info = zipfile.ZipInfo(
                    path.relative_to(test_data).as_posix(), FIXED_TIME
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, path.read_bytes())
        with target.open("rb") as f:
            sha256 = hashlib.file_digest(f, "sha256").hexdigest()
        size_mb = target.stat().st_size / 1e6
        print(f"{archive.name}  {len(files)} files  {size_mb:.1f} MB  sha256 {sha256}")


def main() -> None:
    """Parse the arguments and build the zips."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="folder for the zips")
    parser.add_argument(
        "test_data",
        type=Path,
        nargs="?",
        default=DEFAULT_TEST_DATA,
        help=f"test data folder (default: {DEFAULT_TEST_DATA})",
    )
    args = parser.parse_args()
    if not args.test_data.is_dir():
        sys.exit(
            f"No test data at {args.test_data}; run `git submodule update --init` first"
        )
    build(args.out, args.test_data)


if __name__ == "__main__":
    main()
