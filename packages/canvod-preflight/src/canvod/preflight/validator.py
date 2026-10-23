"""Pre-pipeline validation of data directories against naming convention.

The ``DataDirectoryValidator`` ensures every file entering the pipeline can be
mapped to a ``CanVODFilename``.  Validation is a hard gate: if any files are
unmatched or temporal overlaps exist, processing is blocked with a clear
diagnostic message.

.. deprecated::
    Left over from development and removed with the next major version.
    ``canvodpy config validate`` checks a site's data with the file
    discovery of ``canvodpy run`` (any folder layout, naming recipes).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from canvod.utils.tools import deprecated

from .config_models import ReceiverNamingConfig, SiteNamingConfig
from .convention import FileType
from .mapping import FilenameMapper, VirtualFile

# Map reader_format config values to accepted FileType(s)
_READER_FORMAT_FILETYPES: dict[str, set[FileType]] = {
    "rinex3": {FileType.RNX},
    "rinex": {FileType.RNX},
    "sbf": {FileType.SBF},
}


@dataclass
class ValidationReport:
    """Result of validating a receiver's data directory."""

    matched: list[VirtualFile] = field(default_factory=list)
    unmatched: list[Path] = field(default_factory=list)
    overlaps: list[tuple[VirtualFile, VirtualFile]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_format: list[VirtualFile] = field(default_factory=list)
    files_discovered: int = 0

    @property
    def is_valid(self) -> bool:
        """True if no blocking issues found.

        Returns False when:
        - Any files could not be mapped (unmatched > 0)
        - Any temporal overlaps were detected
        - Files were discovered by the glob patterns but NONE could be parsed
          (matched=0 and unmatched=0 and files_discovered>0 — indicates a
          naming pattern or directory layout mismatch)

        Returns True for a genuinely empty directory (files_discovered=0,
        matched=0) — no data yet is not an error.
        """
        if self.files_discovered > 0 and not self.matched and not self.unmatched:
            return False
        return not self.unmatched and not self.overlaps


@deprecated(
    "DataDirectoryValidator is left over from development and will be removed with the next major version. "
    "Use canvodpy config validate instead."
)
class DataDirectoryValidator:
    """Pre-pipeline validation of data directories against naming convention."""

    def validate_receiver(
        self,
        site_naming: SiteNamingConfig,
        receiver_naming: ReceiverNamingConfig,
        receiver_type: Literal["reference", "canopy"],
        receiver_base_dir: Path,
        reader_format: str | None = None,
    ) -> ValidationReport:
        """Validate all files in a receiver directory.

        Parameters
        ----------
        site_naming
            Site-level naming config.
        receiver_naming
            Receiver-level naming config.
        receiver_type
            ``"reference"`` or ``"canopy"``.
        receiver_base_dir
            Absolute path to the receiver's data directory.
        reader_format
            If set (e.g. ``"rinex3"``, ``"sbf"``), only validate files
            matching that format.  Files of other formats are skipped
            (reported in ``skipped_format``).  ``"auto"`` or ``None``
            validates all formats.

        Returns
        -------
        ValidationReport

        Raises
        ------
        ValueError
            If validation fails (unmatched files, overlaps, or files found
            but none parseable).
        """
        # Constructing the validator already warned about the deprecation.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", ".*left over from development", FutureWarning
            )
            mapper = FilenameMapper(
                site_naming=site_naming,
                receiver_naming=receiver_naming,
                receiver_type=receiver_type,
                receiver_base_dir=receiver_base_dir,
            )

        report = ValidationReport()

        all_physical = mapper._discover_files()
        report.files_discovered = len(all_physical)

        accepted_types: set[FileType] | None = None
        if reader_format and reader_format != "auto":
            accepted_types = _READER_FORMAT_FILETYPES.get(reader_format)

        for path in all_physical:
            try:
                vf = mapper.map_single_file(path)
            except ValueError, KeyError:
                report.unmatched.append(path)
                continue

            if accepted_types and vf.conventional_name.file_type not in accepted_types:
                report.skipped_format.append(vf)
                continue

            report.matched.append(vf)

        seen_names: dict[str, VirtualFile] = {}
        for vf in report.matched:
            name = vf.canonical_str
            if name in seen_names:
                report.warnings.append(
                    f"Duplicate canonical name '{name}': "
                    f"{seen_names[name].physical_path} and {vf.physical_path}"
                )
            else:
                seen_names[name] = vf

        report.overlaps = FilenameMapper.detect_overlaps(report.matched)

        if not report.is_valid:
            raise ValueError(_format_validation_error(report, receiver_base_dir))

        return report


def _format_validation_error(report: ValidationReport, base_dir: Path) -> str:
    """Format a plain-language diagnostic for validation failures.

    Uses physical filenames (what the user created), never canonical names
    (an internal implementation detail the user never sees).
    """
    lines = [f"Data directory validation failed for {base_dir}:"]

    if not report.matched and not report.unmatched:
        lines.append("\n  No data files found. Check that:")
        lines.append("    - The directory path is correct")
        lines.append("    - The directory_layout setting matches your folder structure")
        lines.append(f"    - Files are present (run: ls {base_dir})")
        return "\n".join(lines)

    if not report.matched and report.unmatched:
        lines.append(
            f"\n  None of the {len(report.unmatched)} file(s) matched the expected"
            " naming pattern. First few unrecognised files:"
        )
        for p in report.unmatched[:5]:
            lines.append(f"    - {p.name}")
        if len(report.unmatched) > 5:
            lines.append(f"    ... and {len(report.unmatched) - 5} more")
        lines.append(
            "\n  If these ARE your data files, check the 'naming:' section of"
            " the site in canvod-settings.yaml: the source_pattern or directory_layout may not match"
            " your filenames."
        )
        return "\n".join(lines)

    if report.unmatched:
        lines.append(
            f"\n  {len(report.unmatched)} file(s) could not be recognized as GNSS data:"
        )
        for p in report.unmatched[:10]:
            lines.append(f"    - {p.name}")
        if len(report.unmatched) > 10:
            lines.append(f"    ... and {len(report.unmatched) - 10} more")
        lines.append(
            "  If they are data files, check your source_pattern setting."
            " Hidden files (.DS_Store, Thumbs.db) can be safely ignored."
        )

    if report.overlaps:
        lines.append(
            f"\n  {len(report.overlaps)} pair(s) of files cover the same time period:"
        )
        for vf_a, vf_b in report.overlaps[:5]:
            lines.append(
                f"    - {vf_a.physical_path.name} overlaps {vf_b.physical_path.name}"
            )
        if len(report.overlaps) > 5:
            lines.append(f"    ... and {len(report.overlaps) - 5} more")
        lines.append("  Keep EITHER the daily file OR the sub-daily files, not both.")

    return "\n".join(lines)
