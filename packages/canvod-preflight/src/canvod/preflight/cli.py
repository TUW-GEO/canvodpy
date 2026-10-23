"""CLI entry point: canvod-preflight <dir> (deprecated, use canvodpy config validate)."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="canvod-preflight",
    help="Pre-flight validation of GNSS-T data directories.",
    no_args_is_help=True,
)


@app.command()
def validate(
    data_dir: Path = typer.Argument(  # noqa: B008
        ...,
        help="Receiver data directory to validate.",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    site_id: str = typer.Option(..., "--site", "-s", help="3-char site ID (e.g. ROS)."),
    agency: str = typer.Option(
        ..., "--agency", "-a", help="3-char agency ID (e.g. TUW)."
    ),
    receiver_number: int = typer.Option(
        1, "--receiver", "-r", help="Receiver number (1-99)."
    ),
    receiver_type: str = typer.Option(
        "canopy",
        "--type",
        "-t",
        help="Receiver role: 'canopy' or 'reference'.",
    ),
    layout: str = typer.Option(
        "yyddd_subdirs",
        "--layout",
        "-l",
        help="Directory layout: yyddd_subdirs | yyyyddd_subdirs | flat.",
    ),
    reader_format: str = typer.Option(
        "auto",
        "--format",
        "-f",
        help="Expected file format: auto | rinex3 | sbf.",
    ),
) -> None:
    """Validate a receiver data directory against the canVOD naming convention.

    Deprecated: use ``canvodpy config validate`` instead.
    """
    import warnings

    warnings.warn(
        "The canvod-preflight command is left over from development and will be removed with the next major version. "
        "Use canvodpy config validate instead.",
        FutureWarning,
        stacklevel=1,
    )
    from .config_models import DirectoryLayout, ReceiverNamingConfig, SiteNamingConfig
    from .validator import DataDirectoryValidator

    try:
        layout_enum = DirectoryLayout(layout)
    except ValueError:
        typer.echo(
            f"Unknown layout '{layout}'. "
            f"Valid values: {', '.join(d.value for d in DirectoryLayout)}",
            err=True,
        )
        raise typer.Exit(1) from None

    if receiver_type not in ("canopy", "reference"):
        typer.echo(
            f"Unknown receiver type '{receiver_type}'. Valid values: canopy, reference",
            err=True,
        )
        raise typer.Exit(1) from None

    # One warning for the deprecated command, not one per class it uses.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", ".*left over from development", FutureWarning)
        site_naming = SiteNamingConfig(site_id=site_id, agency=agency)
        receiver_naming = ReceiverNamingConfig(
            receiver_number=receiver_number,
            directory_layout=layout_enum,
        )
        validator = DataDirectoryValidator()
    try:
        report = validator.validate_receiver(
            site_naming=site_naming,
            receiver_naming=receiver_naming,
            receiver_type=receiver_type,
            receiver_base_dir=data_dir,
            reader_format=reader_format if reader_format != "auto" else None,
        )
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None

    typer.echo(
        f"OK: {len(report.matched)} file(s) validated in {data_dir.name}",
    )
    if report.skipped_format:
        typer.echo(
            f"  Skipped {len(report.skipped_format)} file(s) with non-matching format."
        )
    if report.warnings:
        for w in report.warnings:
            typer.echo(f"  Warning: {w}")


if __name__ == "__main__":
    app()
