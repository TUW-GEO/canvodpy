"""Research site and receiver configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from canvod.utils.tools import deprecated

from .base import _StrictModel


class ReceiverHardwareConfig(_StrictModel):
    """The GNSS receiver itself, for the store metadata. All optional."""

    manufacturer: str | None = Field(None, description="Receiver manufacturer")
    model: str | None = Field(None, description="Receiver model")
    serial_number: str | None = Field(None, description="Receiver serial number")
    firmware: str | None = Field(None, description="Firmware version")


class AntennaConfig(_StrictModel):
    """The receiver's antenna, for the store metadata. All optional."""

    manufacturer: str | None = Field(None, description="Antenna manufacturer")
    model: str | None = Field(None, description="Antenna model, as its IGS name")
    radome: str | None = Field(None, description="Radome, as its IGS name")
    serial_number: str | None = Field(None, description="Antenna serial number")
    height_m: float | None = Field(None, description="Antenna height in meters")
    choke_ring: bool | None = Field(None, description="Whether a choke ring is used")
    polarization: Literal["RHCP", "LHCP", "dual-pol"] | None = Field(
        None,
        description=(
            "Polarization the antenna receives: 'RHCP' (the standard), 'LHCP' "
            "or 'dual-pol'"
        ),
    )


class ReceiverConfig(_StrictModel):
    """Receiver configuration."""

    type: Literal["reference", "canopy"] = Field(
        ...,
        description=(
            "Receiver role: 'canopy' = placed under the vegetation canopy; "
            "'reference' = open-sky baseline above or outside the canopy. "
            "Wizard prompt: 'Is this receiver under the canopy or in the open sky?'"
        ),
    )
    directory: str = Field(..., description="Subdirectory for receiver data")
    paired_canopies: str | list[str] | None = Field(
        None,
        description=(
            "Which canopy receiver(s) to pair with this reference. "
            "Required for reference receivers: 'all' or a list of canopy names. "
            "Must not be set for canopy receivers."
        ),
    )
    description: str | None = Field(
        None,
        description="Human-readable description",
    )
    naming: dict | None = Field(
        None,
        description=(
            "Deprecated, not used for file discovery. Set 'recipe' for "
            "non-canonical filenames instead."
        ),
    )
    metadata: dict[str, str | int | float | bool] | None = Field(
        None,
        description=(
            "Freeform receiver metadata written to dataset global attrs. "
            "Example keys: site_url, antenna_height, species."
        ),
    )
    receiver_hardware: ReceiverHardwareConfig | None = Field(
        None,
        description=(
            "Optional: the receiver's manufacturer, model, serial number and "
            "firmware, copied into the GNSS store's metadata."
        ),
    )
    antenna: AntennaConfig | None = Field(
        None,
        description=(
            "Optional: the antenna's manufacturer, model and radome (IGS "
            "names), serial number and height, copied into the GNSS store's "
            "metadata."
        ),
    )
    reader_format: str = Field(
        "auto",
        description=(
            "Reader for the receiver's files: 'rinex3' (RINEX 3), "
            "'rinex3_stripped' (RINEX 3 with signal strengths only, faster), "
            "'rinex2' (RINEX 2.11), 'sbf' (Septentrio binary), 'nmea', or the "
            "name of an installed reader plugin. "
            "'auto': detected per day from the files (SBF and NMEA by file "
            "type, RINEX 2 or 3 from the header; never a plugin); a day whose "
            "files need different readers is an error."
        ),
    )

    @field_validator("reader_format")
    @classmethod
    def _known_reader_format(cls, v: str) -> str:
        known = reader_formats()
        if v not in known:
            raise ValueError(
                f"Unknown reader_format {v!r}. Known: {', '.join(known)}. A "
                "reader plugin is known once its package is installed."
            )
        return v

    recipe: str | None = Field(
        None,
        description=(
            "Name of a naming recipe (e.g. 'examplesite_reference'). "
            "Read from <config dir>/recipes/<site>/{recipe}.yaml. "
            "Without a recipe, only files with canonical canVOD names are "
            "processed."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_scs_from(cls, data: object) -> object:
        if isinstance(data, dict) and "scs_from" in data:
            import warnings

            warnings.warn(
                "The receiver setting 'scs_from' is left over from development and will be removed with the next major version. "
                "Rename it to 'paired_canopies' in your site configuration.",
                FutureWarning,
                stacklevel=2,
            )
            data = dict(data)
            data["paired_canopies"] = data.pop("scs_from")
        return data

    @model_validator(mode="before")
    @classmethod
    def _warn_naming(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("naming") is not None:
            import warnings

            warnings.warn(
                "The receiver setting 'naming' is left over from development and will be removed with the next major version. "
                "Use 'recipe' instead (create one with: just naming-init <site> <recipe>).",
                FutureWarning,
                stacklevel=2,
            )
        return data

    @model_validator(mode="after")
    def validate_paired_canopies(self) -> ReceiverConfig:
        """Validate paired_canopies is required for reference, forbidden for canopy."""
        if self.type == "reference" and self.paired_canopies is None:
            msg = "paired_canopies is required for reference receivers"
            raise ValueError(msg)
        if self.type == "canopy" and self.paired_canopies is not None:
            msg = "paired_canopies must not be set for canopy receivers"
            raise ValueError(msg)
        return self


def reference_store_group(reference_receiver: str, canopy_receiver: str) -> str:
    """Icechunk store group name holding a reference receiver's paired data.

    Reference receiver data is always written to the GNSS store under this
    paired name (see ``PipelineOrchestrator._group_by_date_and_receiver``),
    never under the bare receiver name -- one reference can be paired with
    several canopies, each getting its own group. This is the single place
    that derives that name; every reader of the store should call this (or
    ``VodAnalysisConfig.reference_store_group``) instead of formatting the
    f-string locally.

    Parameters
    ----------
    reference_receiver : str
        Bare reference receiver name (matches a ``receivers`` config key).
    canopy_receiver : str
        Bare canopy receiver name it is paired with.

    Returns
    -------
    str
        Store group name, e.g. ``"reference_01_canopy_01"``.
    """
    return f"{reference_receiver}_{canopy_receiver}"


#: File format read by each reader format; ``rinex3_stripped`` reads RINEX 3.
_FILE_FORMAT: dict[str, str] = {"rinex3_stripped": "rinex3"}

#: Reader formats of canvodpy itself; plugins add more (:func:`reader_formats`).
BUILT_IN_READER_FORMATS = ("auto", "rinex3", "rinex3_stripped", "rinex2", "sbf", "nmea")


def reader_formats() -> list[str]:
    """Values ``reader_format`` accepts: the built-in formats and plugins.

    Plugin names come from the entry point group ``canvodpy.readers`` of
    the installed packages, without importing them.
    """
    from canvod.utils.plugins import READER_GROUP, plugin_names

    return [*BUILT_IN_READER_FORMATS, *plugin_names(READER_GROUP)]


def mixed_format_error(
    canopy: str, canopy_format: str, reference: str, reference_format: str
) -> str | None:
    """Error message if a canopy and its reference record different file formats.

    A canopy receiver and its reference receiver must record the same file
    format (e.g. both SBF): the reference's position is read from the
    canopy's files with the reference's reader, and both receivers' epochs
    must be in the same time scale. ``"auto"`` is not checked here; check
    again once the format is detected from the files.

    Returns
    -------
    str | None
        The message, or ``None`` if the formats agree or one is ``"auto"``.
    """
    if "auto" in (canopy_format, reference_format):
        return None
    if _FILE_FORMAT.get(canopy_format, canopy_format) == _FILE_FORMAT.get(
        reference_format, reference_format
    ):
        return None
    return (
        f"Canopy receiver '{canopy}' records {canopy_format!r} files, its "
        f"reference receiver '{reference}' records {reference_format!r} files. "
        "A canopy and its reference must record the same file format; "
        "mixed formats are not supported."
    )


class VodAnalysisConfig(_StrictModel):
    """VOD analysis pair configuration."""

    canopy_receiver: str = Field(..., description="Canopy receiver name")
    reference_receiver: str = Field(
        ...,
        description=(
            "Bare reference receiver name -- always matches a 'receivers' "
            "config key, never a store group name. Used for directory "
            "lookups during RINEX ingest. For the Icechunk store group "
            "holding this receiver's data (paired with canopy_receiver), "
            "use the reference_store_group property instead."
        ),
    )
    description: str | None = Field(None, description="Analysis description")

    @property
    def reference_store_group(self) -> str:
        """Icechunk store group name for this analysis's reference data.

        See :func:`reference_store_group` (module-level) for why this is
        distinct from ``reference_receiver``.
        """
        return reference_store_group(self.reference_receiver, self.canopy_receiver)


class SiteConfig(_StrictModel):
    """Research site configuration."""

    gnss_site_data_root: str = Field(
        ..., description="Root directory for site GNSS data"
    )
    description: str | None = Field(None, description="Site description")
    store_description: str | None = Field(
        None,
        description=(
            "What the site's stores hold (e.g. 'GNSS-T observations below "
            "a beech canopy'): written to StoreIdentity.description. "
            "Required when a store of the site is created."
        ),
    )
    country: str | None = Field(None, description="Country code (ISO 3166-1)")
    latitude: float | None = Field(None, description="WGS84 latitude")
    longitude: float | None = Field(None, description="WGS84 longitude")
    altitude_m: float | None = Field(None, description="Altitude in meters")
    receivers: dict[str, ReceiverConfig] = Field(..., description="Site receivers")
    vod_analyses: dict[str, VodAnalysisConfig] | None = Field(
        None,
        description="VOD analysis pairs",
    )
    naming: dict | None = Field(
        None,
        description=(
            "Deprecated, not used for file discovery. Set 'recipe' on each "
            "receiver with non-canonical filenames instead."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _warn_naming(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("naming") is not None:
            import warnings

            warnings.warn(
                "The site setting 'naming' is left over from development and will be removed with the next major version. "
                "Use 'recipe' on each receiver instead (create one with: just naming-init <site> <recipe>).",
                FutureWarning,
                stacklevel=2,
            )
        return data

    @model_validator(mode="after")
    def validate_paired_canopies_targets(self) -> SiteConfig:
        """Validate that paired_canopies entries reference existing canopy receivers."""
        canopy_names = self.get_canopy_receiver_names()
        for name, cfg in self.receivers.items():
            if cfg.type != "reference" or cfg.paired_canopies is None:
                continue
            if isinstance(cfg.paired_canopies, str) and cfg.paired_canopies == "all":
                continue
            targets = (
                cfg.paired_canopies
                if isinstance(cfg.paired_canopies, list)
                else [cfg.paired_canopies]
            )
            for target in targets:
                if target not in canopy_names:
                    msg = (
                        f"Receiver '{name}' paired_canopies references '{target}' "
                        f"which is not a canopy receiver. "
                        f"Available canopy receivers: {canopy_names}"
                    )
                    raise ValueError(msg)
        return self

    def get_base_path(self) -> Path:
        """Get gnss_site_data_root as a Path.

        Returns
        -------
        Path
            Site data root directory as a Path object.
        """
        return Path(self.gnss_site_data_root)

    def get_canopy_receiver_names(self) -> list[str]:
        """Get names of all canopy receivers.

        Returns
        -------
        list[str]
            Canopy receiver names.
        """
        return [name for name, cfg in self.receivers.items() if cfg.type == "canopy"]

    def resolve_paired_canopies(self, receiver_name: str) -> list[str]:
        """Resolve paired_canopies for a reference receiver to a list of canopy names.

        Parameters
        ----------
        receiver_name : str
            Name of the reference receiver.

        Returns
        -------
        list[str]
            List of canopy receiver names paired with this reference.
        """
        cfg = self.receivers[receiver_name]
        if cfg.type != "reference":
            msg = f"resolve_paired_canopies only applies to reference receivers, got '{cfg.type}'"
            raise ValueError(msg)
        if cfg.paired_canopies == "all":
            return self.get_canopy_receiver_names()
        if isinstance(cfg.paired_canopies, list):
            return cfg.paired_canopies
        # Single canopy name as string
        if cfg.paired_canopies is None:
            msg = f"Receiver '{receiver_name}' has no paired_canopies configured"
            raise ValueError(msg)
        return [cfg.paired_canopies]

    @deprecated(
        "SiteConfig.resolve_scs_from() is left over from development and will be removed with the next major version. "
        "Use SiteConfig.resolve_paired_canopies() instead."
    )
    def resolve_scs_from(self, receiver_name: str) -> list[str]:
        """Deprecated: use resolve_paired_canopies instead."""
        return self.resolve_paired_canopies(receiver_name)

    @model_validator(mode="after")
    def _auto_derive_vod_analyses(self) -> SiteConfig:
        """Fill vod_analyses from paired_canopies when not explicitly set."""
        if self.vod_analyses is not None:
            return self
        pairs = self.get_reference_canopy_pairs()
        if not pairs:
            return self
        self.vod_analyses = {
            f"{canopy}_vs_{ref}": VodAnalysisConfig(
                canopy_receiver=canopy,
                reference_receiver=ref,
            )
            for ref, canopy in pairs
        }
        return self

    @model_validator(mode="after")
    def validate_same_file_format(self) -> SiteConfig:
        """Reject a canopy and reference that record different file formats."""
        pairs = set(self.get_reference_canopy_pairs())
        pairs |= {
            (a.reference_receiver, a.canopy_receiver)
            for a in (self.vod_analyses or {}).values()
        }
        for ref, canopy in sorted(pairs):
            if ref not in self.receivers or canopy not in self.receivers:
                continue
            msg = mixed_format_error(
                canopy,
                self.receivers[canopy].reader_format,
                ref,
                self.receivers[ref].reader_format,
            )
            if msg:
                raise ValueError(msg)
        return self

    def get_reference_canopy_pairs(self) -> list[tuple[str, str]]:
        """Expand paired_canopies into (reference_name, canopy_name) pairs.

        Returns
        -------
        list[tuple[str, str]]
            List of (reference_name, canopy_name) pairs.
        """
        pairs = []
        for name, cfg in self.receivers.items():
            if cfg.type != "reference":
                continue
            for canopy_name in self.resolve_paired_canopies(name):
                pairs.append((name, canopy_name))
        return pairs


class SitesConfig(_StrictModel):
    """All research sites.

    An empty ``sites: {}`` is a valid, unwarned state: config loading is a
    foundation-layer concern used by every ``canvod-*`` package, most of
    which never touch sites at all (see ``CLAUDE.md``'s "package-standalone
    usage" goal). The actionable error for a *missing* site belongs at the
    point where a site is actually looked up by name --
    ``GnssResearchSite.__init__`` (canvod-store/manager.py) already raises
    a ``KeyError`` listing available sites there.
    """

    sites: dict[str, SiteConfig]
