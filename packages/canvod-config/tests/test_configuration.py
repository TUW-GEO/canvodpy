"""Tests that the YAML configuration system loads a complete config.

Uses the shipped ``canvod-settings.yaml.example`` template (the file
``canvodpy config init`` copies), with the placeholder author/email filled
in, so the tests run on every checkout instead of depending on a
user-specific ``config/`` directory:

1. Config loads from ``canvod-settings.yaml``
2. Credentials are read from ``processing.credentials``
3. Every site has a ``gnss_site_data_root``
4. The template's placeholder metadata is rejected until filled in
"""

from pathlib import Path

import pytest

from canvod.config import load_config
from canvod.config.loader import ConfigValidationError, get_template_dir

_PLACEHOLDERS = {
    "Your Name": "Test Author",
    "your.email@example.com": "test.author@example.org",
}


def _template_text() -> str:
    return (get_template_dir() / "canvod-settings.yaml.example").read_text()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A config directory holding the template with real metadata filled in."""
    text = _template_text()
    for placeholder, value in _PLACEHOLDERS.items():
        assert placeholder in text, f"template no longer contains {placeholder!r}"
        text = text.replace(placeholder, value)
    (tmp_path / "canvod-settings.yaml").write_text(text)
    load_config.cache_clear()
    yield tmp_path
    load_config.cache_clear()


def test_config_loads(config_dir: Path):
    """Config loads from canvod-settings.yaml."""
    config = load_config(config_dir=config_dir)

    assert config.processing.metadata.author == "Test Author"
    assert config.processing.aux_data.agency is not None
    assert len(config.sites.sites) > 0


def test_credentials_from_yaml(config_dir: Path):
    """Credentials are read from processing.credentials (with defaults)."""
    config = load_config(config_dir=config_dir)

    assert config.processing.credentials is not None
    # The property should work
    _ = config.nasa_earthdata_acc_mail


def test_site_data_roots(config_dir: Path):
    """Each site has gnss_site_data_root."""
    config = load_config(config_dir=config_dir)

    for site in config.sites.sites.values():
        assert site.gnss_site_data_root is not None
        assert isinstance(site.get_base_path(), Path)


def test_template_placeholders_are_rejected(tmp_path: Path):
    """The unedited template fails validation on its placeholder metadata."""
    (tmp_path / "canvod-settings.yaml").write_text(_template_text())
    load_config.cache_clear()
    try:
        with pytest.raises(ConfigValidationError, match="placeholder"):
            load_config(config_dir=tmp_path)
    finally:
        load_config.cache_clear()


def test_imports():
    """Test all critical imports work."""
    from canvod.config.models import (
        CredentialsConfig,
    )

    # CredentialsConfig should work with defaults
    creds = CredentialsConfig()
    assert creds.nasa_earthdata_acc_mail is None

    # CredentialsConfig should accept an email
    creds_with_mail = CredentialsConfig(nasa_earthdata_acc_mail="test@example.com")
    assert creds_with_mail.nasa_earthdata_acc_mail == "test@example.com"


def test_the_repository_template_is_the_shipped_one():
    """``config/canvod-settings.yaml.example`` is a copy of the shipped template.

    Edit the shipped one (``canvod/config/templates/``) and copy it.
    """
    repository_copy = (
        Path(__file__).parents[3] / "config" / "canvod-settings.yaml.example"
    )
    if not repository_copy.exists():
        pytest.skip("not run from a canvodpy checkout")
    assert repository_copy.read_text() == _template_text(), (
        "config/canvod-settings.yaml.example differs from the shipped template: "
        "copy packages/canvod-config/src/canvod/config/templates/"
        "canvod-settings.yaml.example over it"
    )
