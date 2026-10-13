"""Human-readable metadata display and query tool.

Usage
-----
    from canvod.store_metadata import show_metadata
    show_metadata("/path/to/store")                  # full report
    show_metadata("/path/to/store", section="env")   # just environment
    show_metadata("/path/to/store", section="uv")    # dump uv.lock
"""

from __future__ import annotations

import sys
import textwrap
import warnings
from pathlib import Path
from typing import Any

from .io import amendments_since, read_metadata
from .location import (
    LocalStoreLocation,
    StoreLocation,
    open_repository,
    store_location,
)
from .schema import StoreMetadata
from .validate import validate_all


def _hr(char: str = "─", width: int = 72) -> str:
    return char * width


def _section(title: str, width: int = 72) -> str:
    pad = width - len(title) - 4
    return f"┌─ {title} {'─' * max(pad, 0)}┐"


def _kv(key: str, value: Any, indent: int = 2) -> str:
    prefix = " " * indent
    if value is None:
        return f"{prefix}{key}: (not set)"
    if isinstance(value, list) and len(value) > 5:
        first = ", ".join(str(v) for v in value[:3])
        return f"{prefix}{key}: [{first}, ... +{len(value) - 3} more]"
    return f"{prefix}{key}: {value}"


def _dict_block(d: dict[str, Any], indent: int = 4) -> str:
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{' ' * indent}{k}:")
            lines.append(_dict_block(v, indent + 2))
        elif isinstance(v, list) and len(v) > 3:
            lines.append(f"{' ' * indent}{k}: [{len(v)} items]")
        else:
            lines.append(f"{' ' * indent}{k}: {v}")
    return "\n".join(lines)


def format_identity(meta: StoreMetadata) -> str:
    s = meta.identity
    lines = [_section("Identity & Discovery")]
    lines.append(_kv("ID", s.id))
    lines.append(_kv("Title", s.title))
    lines.append(_kv("Description", s.description))
    lines.append(_kv("Store type", s.store_type))
    lines.append(_kv("Source format", s.source_format))
    lines.append(_kv("Keywords", s.keywords))
    lines.append(_kv("Conventions", s.conventions))
    lines.append(_kv("Naming authority", s.naming_authority))
    return "\n".join(lines)


def format_creator(meta: StoreMetadata) -> str:
    c = meta.creator
    lines = [_section("Creator")]
    lines.append(_kv("Name", c.name))
    lines.append(_kv("Email", c.email))
    lines.append(_kv("ORCID", c.orcid))
    lines.append(_kv("Institution", c.institution))
    lines.append(_kv("ROR", c.institution_ror))
    lines.append(_kv("Department", c.department))
    lines.append(_kv("Research group", c.research_group))
    lines.append(_kv("Website", c.website))
    return "\n".join(lines)


def format_publisher(meta: StoreMetadata) -> str:
    p = meta.publisher
    lines = [_section("Publisher & Rights")]
    lines.append(_kv("Publisher", p.name))
    lines.append(_kv("Type", p.type))
    lines.append(_kv("URL", p.url))
    lines.append(_kv("License", p.license))
    lines.append(_kv("License URI", p.license_uri))
    return "\n".join(lines)


def format_temporal(meta: StoreMetadata) -> str:
    t = meta.temporal
    lines = [_section("Temporal Extent")]
    lines.append(_kv("Created", t.created))
    lines.append(_kv("Updated", t.updated))
    lines.append(_kv("Data start", t.collected_start))
    lines.append(_kv("Data end", t.collected_end))
    lines.append(_kv("Duration", t.time_coverage_duration))
    lines.append(_kv("Resolution", t.time_coverage_resolution))
    return "\n".join(lines)


def format_spatial(meta: StoreMetadata) -> str:
    sp = meta.spatial
    lines = [_section("Spatial Extent & Site")]
    lines.append(_kv("Site", sp.site.name))
    lines.append(_kv("Description", sp.site.description))
    lines.append(_kv("Country", sp.site.country))
    if sp.geospatial_lat is not None:
        lines.append(
            _kv(
                "Position",
                f"{sp.geospatial_lat:.4f}N, "
                f"{sp.geospatial_lon:.4f}E, "
                f"{sp.geospatial_alt_m}m",
            )
        )
    lines.append(_kv("CRS", sp.geospatial_vertical_crs))
    lines.append(_kv("STAC bbox", sp.bbox))
    return "\n".join(lines)


def format_instruments(meta: StoreMetadata) -> str:
    inst = meta.instruments
    lines = [_section("Instruments & Receivers")]
    lines.append(_kv("Platform", inst.platform))
    lines.append(_kv("Instruments", inst.instruments))
    for name, rcv in inst.receivers.items():
        lines.append(f"    {name}:")
        lines.append(_kv("type", rcv.type, indent=6))
        lines.append(_kv("directory", rcv.directory, indent=6))
        lines.append(_kv("format", rcv.reader_format, indent=6))
        lines.append(_kv("description", rcv.description, indent=6))
        lines.append(_kv("recipe", rcv.recipe, indent=6))
        if rcv.epochs is not None:
            lines.append(_kv("epochs", rcv.epochs, indent=6))
        if rcv.sids is not None:
            lines.append(_kv("sids", rcv.sids, indent=6))
    return "\n".join(lines)


def format_processing(meta: StoreMetadata) -> str:
    p = meta.processing
    lines = [_section("Software Provenance")]
    lines.append(_kv("Level", p.level))
    lines.append(_kv("Python", p.python))
    lines.append(_kv("uv", p.uv_version))
    lines.append(_kv("Facility", p.facility))
    lines.append(_kv("Timestamp", p.datetime))
    lines.append(_kv("Lineage", p.lineage))
    if p.software:
        lines.append("    Packages:")
        for pkg, ver in sorted(p.software.items()):
            lines.append(f"      {pkg}: {ver}")
    return "\n".join(lines)


def format_environment(meta: StoreMetadata) -> str:
    e = meta.environment
    lines = [_section("Environment")]
    lines.append(_kv("Hostname", e.hostname))
    lines.append(_kv("OS", e.os))
    lines.append(_kv("Arch", e.arch))
    lines.append(_kv("CPUs", e.cpu_count))
    lines.append(_kv("RAM (GB)", e.memory_gb))
    lines.append(_kv("Disk free (GB)", e.disk_free_gb))
    lines.append(_kv("Dask workers", e.dask_workers))
    lines.append(_kv("Threads/worker", e.dask_threads_per_worker))
    lines.append(_kv("uv.lock hash", e.uv_lock_hash))
    has_toml = e.pyproject_toml_text is not None
    has_lock = e.uv_lock_text is not None
    pyproject_text = e.pyproject_toml_text if has_toml else None
    uv_lock_text = e.uv_lock_text if has_lock else None
    pyproject_desc = (
        f"stored ({len(pyproject_text)} chars)"
        if pyproject_text is not None
        else "(not stored)"
    )
    uv_lock_desc = (
        f"stored ({len(uv_lock_text)} chars)"
        if uv_lock_text is not None
        else "(not stored)"
    )
    lines.append(
        _kv(
            "pyproject.toml",
            pyproject_desc,
        )
    )
    lines.append(
        _kv(
            "uv.lock",
            uv_lock_desc,
        )
    )
    return "\n".join(lines)


def format_config(meta: StoreMetadata) -> str:
    c = meta.config
    lines = [_section("Config Snapshot")]
    lines.append(_kv("Config hash", c.config_hash))
    for section_name in (
        "processing",
        "preprocessing",
        "aux_data",
        "netcdf_compression",
        "icechunk",
        "sids",
    ):
        val = getattr(c, section_name, None)
        if val is not None:
            lines.append(f"    {section_name}:")
            lines.append(_dict_block(val, indent=6))
    return "\n".join(lines)


def format_references(meta: StoreMetadata) -> str:
    r = meta.references
    lines = [_section("References")]
    lines.append(_kv("Repository", r.software_repository))
    lines.append(_kv("Documentation", r.documentation))
    lines.append(_kv("Related stores", r.related_stores))
    if r.publications:
        lines.append("    Publications:")
        for p in r.publications:
            lines.append(f"      - {p.doi}")
            if p.citation:
                lines.append(f"        {p.citation}")
    if r.funding:
        lines.append("    Funding:")
        for f in r.funding:
            lines.append(f"      - {f.funder}")
            if f.grant_number:
                lines.append(f"        Grant: {f.grant_number}")
    return "\n".join(lines)


def format_summaries(meta: StoreMetadata) -> str:
    s = meta.summaries
    lines = [_section("Summaries")]
    lines.append(_kv("Total epochs", s.total_epochs))
    lines.append(_kv("Total SIDs", s.total_sids))
    lines.append(_kv("Constellations", s.constellations))
    lines.append(_kv("Variables", s.variables))
    lines.append(_kv("Temporal res (s)", s.temporal_resolution_s))
    lines.append(_kv("File count", s.file_count))
    lines.append(_kv("Store size (MB)", s.store_size_mb))
    # Only snapshots written before the migration have a stored history;
    # the history of every other snapshot is its commit log.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        history = s.history
    if history:
        lines.append("    History (stored before migration):")
        for entry in history[-10:]:
            lines.append(f"      {entry}")
        if len(history) > 10:
            lines.append(f"      ... +{len(history) - 10} older entries")
    return "\n".join(lines)


def format_validation(meta: StoreMetadata, store_path: Path | None = None) -> str:
    """Failures per standard, then the recommendations, FAIR advice and
    warnings.

    ``store_path``, the local store ``meta`` comes from, adds the warning
    about a catalog link without an item file (:func:`validate_all`).
    """
    failures = validate_all(meta, recommended=False)
    results = validate_all(meta, store_path=store_path)
    lines = [_section("FAIR & Compliance Validation")]
    for standard, issues in results.items():
        failed = failures[standard]
        advice = len(issues) - len(failed)
        status = "PASS" if not failed else f"{len(failed)} failures"
        if advice:
            status += f", {advice} recommendations"
        lines.append(f"    {standard.upper()}: {status}")
        for issue in issues:
            lines.append(f"      - {issue}")
    return "\n".join(lines)


def _sections(store_path: Path | None = None) -> dict[str, Any]:
    """Section name to formatter; ``store_path`` goes to the validation."""
    return {
        "identity": format_identity,
        "creator": format_creator,
        "publisher": format_publisher,
        "temporal": format_temporal,
        "spatial": format_spatial,
        "instruments": format_instruments,
        "processing": format_processing,
        "env": format_environment,
        "config": format_config,
        "references": format_references,
        "summaries": format_summaries,
        "validation": lambda meta: format_validation(meta, store_path),
    }


def format_metadata(
    meta: StoreMetadata,
    section: str | None = None,
    *,
    store_path: Path | None = None,
) -> str:
    """Format metadata as a human-readable string.

    Parameters
    ----------
    meta : StoreMetadata
        The metadata to format.
    section : str | None
        If given, show only this section. Special values:
        - "uv" / "uv.lock": dump raw uv.lock content
        - "toml" / "pyproject": dump raw pyproject.toml content
        - "env-reproduce": print instructions to reproduce env
        - Any section name of :func:`_sections`: show that section only
        If None, show full report.
    store_path : Path | None
        The local store ``meta`` comes from, for the validation section
        (:func:`format_validation`).
    """
    sections = _sections(store_path)
    if section in ("uv", "uv.lock"):
        if meta.environment.uv_lock_text:
            return meta.environment.uv_lock_text
        return "(uv.lock not stored in this metadata)"

    if section in ("toml", "pyproject", "pyproject.toml"):
        if meta.environment.pyproject_toml_text:
            return meta.environment.pyproject_toml_text
        return "(pyproject.toml not stored in this metadata)"

    if section in ("env-reproduce", "reproduce"):
        return _format_reproduce_instructions(meta)

    if section is not None:
        formatter = sections.get(section)
        if formatter is None:
            available = ", ".join(list(sections) + ["uv", "toml", "reproduce"])
            return f"Unknown section '{section}'. Available: {available}"
        return formatter(meta)

    # Full report
    parts = [
        f"{'=' * 72}",
        "  canvod Store Metadata Report",
        f"  Schema version: {meta.metadata_version}",
        f"{'=' * 72}",
    ]
    for formatter in sections.values():
        parts.append("")
        parts.append(formatter(meta))
    parts.append("")
    parts.append(_hr("="))
    return "\n".join(parts)


def _format_reproduce_instructions(meta: StoreMetadata) -> str:
    """Instructions for reproducing the environment from stored files."""
    has_toml = meta.environment.pyproject_toml_text is not None
    has_lock = meta.environment.uv_lock_text is not None

    if not has_toml or not has_lock:
        missing = []
        if not has_toml:
            missing.append("pyproject.toml")
        if not has_lock:
            missing.append("uv.lock")
        return (
            f"Cannot reproduce: {', '.join(missing)} not stored.\n"
            "Re-ingest with canvod-store-metadata >= 0.1.0."
        )

    return textwrap.dedent("""\
        Environment Reproduction
        ========================
        The store contains the exact pyproject.toml and uv.lock
        used at ingest time. To recreate the environment:

        1. Extract files from the store:

            from canvod.store_metadata import read_metadata
            from pathlib import Path

            meta = read_metadata(Path("your/store"))
            Path("pyproject.toml").write_bytes(
                meta.environment.pyproject_toml_text.encode()
            )
            Path("uv.lock").write_bytes(
                meta.environment.uv_lock_text.encode()
            )

        2. Create the virtual environment:

            uv sync --frozen

        3. Or as a one-liner (Python):

            from canvod.store_metadata.show import extract_env
            extract_env(Path("your/store"), Path("repro_env/"))

        uv.lock hash: {hash}
        Python version: {python}
    """).format(
        hash=meta.environment.uv_lock_hash or "unknown",
        python=meta.processing.python or "unknown",
    )


def extract_env(
    store_path: StoreLocation | Path | str,
    output_dir: Path,
    branch: str = "main",
) -> Path:
    """Extract pyproject.toml + uv.lock from a store for reproduction.

    Parameters
    ----------
    store_path : Path
        Path to the Icechunk store.
    output_dir : Path
        Directory to write the files into.
    branch : str
        Store branch.

    Returns
    -------
    Path
        The output directory (ready for ``uv sync --frozen``).
    """
    meta = read_metadata(store_path, branch)
    output_dir.mkdir(parents=True, exist_ok=True)

    if meta.environment.pyproject_toml_text is None:
        msg = "pyproject.toml not stored in this metadata"
        raise ValueError(msg)
    if meta.environment.uv_lock_text is None:
        msg = "uv.lock not stored in this metadata"
        raise ValueError(msg)

    # Bytes, not text mode: on Windows text mode writes \r\n, and the
    # restored uv.lock would no longer match its recorded hash.
    (output_dir / "pyproject.toml").write_bytes(
        meta.environment.pyproject_toml_text.encode()
    )
    (output_dir / "uv.lock").write_bytes(meta.environment.uv_lock_text.encode())
    return output_dir


def _commit_log(
    store_path: StoreLocation | Path | str, snapshot_id: str, limit: int = 20
) -> list[str]:
    """The newest commits up to ``snapshot_id``: time, message, settings hash."""
    lines = []
    for i, snapshot in enumerate(
        open_repository(store_path).ancestry(snapshot_id=snapshot_id)
    ):
        if i == limit:
            lines.append(f"  ... older commits not shown (the {limit} newest are)")
            break
        config_hash = snapshot.metadata.get("config", {}).get("config_hash")
        settings = f"  (settings {config_hash[:12]})" if config_hash else ""
        lines.append(
            f"  {snapshot.written_at:%Y-%m-%d %H:%M:%S}  {snapshot.message}{settings}"
        )
    return lines


def show_metadata(
    store_path: str | Path,
    section: str | None = None,
    branch: str = "main",
    *,
    snapshot_id: str | None = None,
) -> None:
    """Print store metadata to stdout.

    Parameters
    ----------
    store_path : str | Path
        Path to an Icechunk store.
    section : str | None
        Section to show (None = full report).
    branch : str
        Show the tip of this branch.
    snapshot_id : str | None
        Show this snapshot instead of a branch tip.
    """
    path = store_location(store_path)
    try:
        meta = read_metadata(path, branch, snapshot_id=snapshot_id)
    except KeyError:
        print(f"No metadata found in {path}")
        return
    repo = open_repository(path)
    # Native and inlined chunks: what the store itself holds.
    meta.summaries.store_size_mb = round(
        repo.chunk_storage_stats().non_virtual_bytes() / 1e6, 3
    )
    if meta.written_before_migration:
        print(
            "This snapshot was written before migration: the store kept its "
            "metadata in one attribute then (canvodpy store migrate-metadata)."
        )
    local = path.path if isinstance(path, LocalStoreLocation) else None
    print(format_metadata(meta, section, store_path=local))
    if section is not None:
        return
    since = [] if meta.written_before_migration else amendments_since(path, meta)
    if since:
        print(_section("Amended since this snapshot"))
        for amendment in since:
            print(
                f"  {amendment.when}  {amendment.field}: {amendment.old!r} -> "
                f"{amendment.new!r} ({amendment.reason}; {amendment.who})"
            )
    snapshot = snapshot_id or repo.lookup_branch(branch)
    print(_section("History (commit log)"))
    print("\n".join(_commit_log(path, snapshot)))


# CLI entry point
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m canvod.store_metadata.show <store_path> [section]")
        print(f"Sections: {', '.join(_sections())}, uv, toml, reproduce")
        sys.exit(1)

    store = sys.argv[1]
    sec = sys.argv[2] if len(sys.argv) > 2 else None
    show_metadata(store, section=sec)
