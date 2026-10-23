"""The mapping and validation API of canvod-preflight is deprecated."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from canvod.preflight import (
    DataDirectoryValidator,
    FilenameMapper,
    ReceiverNamingConfig,
    SiteNamingConfig,
    match_pattern,
)
from canvod.preflight.cli import app
from canvod.utils import testing

MESSAGE = "left over from development and will be removed with the next major"


@pytest.mark.parametrize(
    ("make", "replacement"),
    [
        (
            lambda: SiteNamingConfig(site_id=testing.SITE_ID, agency=testing.AGENCY),
            "recipe",
        ),
        (lambda: ReceiverNamingConfig(receiver_number=1), "recipe"),
        (lambda: match_pattern("FANA01INK_R_20250010000_15M_05S_AA.rnx"), "recipe"),
        (DataDirectoryValidator, "canvodpy config validate"),
    ],
)
def test_deprecated_objects_warn(make, replacement) -> None:
    with pytest.warns(FutureWarning, match=MESSAGE) as record:
        make()
    assert replacement in str(record[0].message)


@pytest.mark.filterwarnings("ignore:.*NamingConfig:FutureWarning")
def test_filename_mapper_warns(tmp_path) -> None:
    site = SiteNamingConfig(site_id=testing.SITE_ID, agency=testing.AGENCY)
    receiver = ReceiverNamingConfig(receiver_number=1)
    with pytest.warns(FutureWarning, match="FilenameMapper is " + MESSAGE):
        FilenameMapper(
            site_naming=site,
            receiver_naming=receiver,
            receiver_type="canopy",
            receiver_base_dir=tmp_path,
        )


def test_validate_command_warns(tmp_path) -> None:
    with pytest.warns(FutureWarning, match="canvodpy config validate"):
        CliRunner().invoke(
            app, [str(tmp_path), "-s", testing.SITE_ID, "-a", testing.AGENCY]
        )
