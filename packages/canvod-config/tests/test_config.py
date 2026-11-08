"""The settings models import and give their defaults."""

from canvod.config import load_config
from canvod.config.models import (
    AuxDataConfig,
    CanvodConfig,
    CredentialsConfig,
    ProcessingConfig,
    SidsConfig,
    SitesConfig,
)


def test_public_names_import() -> None:
    assert callable(load_config)
    assert all(
        isinstance(model, type)
        for model in (CanvodConfig, ProcessingConfig, SidsConfig, SitesConfig)
    )


def test_credentials_have_no_email_by_default() -> None:
    assert CredentialsConfig().nasa_earthdata_acc_mail is None


def test_ftp_servers_with_and_without_email() -> None:
    aux_data = AuxDataConfig(agency="COD", product_type="final")

    assert aux_data.get_ftp_servers("test@example.com") == [
        ("ftp://gdc.cddis.eosdis.nasa.gov", "test@example.com"),
        ("ftp://gssc.esa.int", None),
    ]
    assert aux_data.get_ftp_servers(None) == [("ftp://gssc.esa.int", None)]
