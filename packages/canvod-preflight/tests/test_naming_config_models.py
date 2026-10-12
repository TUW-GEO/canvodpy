"""Tests for canvod.preflight.config_models."""

import pytest
from pydantic import ValidationError

from canvod.preflight.config_models import (
    DirectoryLayout,
    ReceiverNamingConfig,
    SiteNamingConfig,
)
from canvod.utils import testing

# Tests of the deprecated mapping and validation API, see test_deprecations.py.
pytestmark = pytest.mark.filterwarnings(
    "ignore:.*left over from development:FutureWarning"
)


class TestSiteNamingConfig:
    def test_minimal(self):
        cfg = SiteNamingConfig(site_id=testing.SITE_ID, agency=testing.AGENCY)
        assert cfg.site_id == testing.SITE_ID
        assert cfg.agency == testing.AGENCY
        assert cfg.default_sampling == "05S"
        assert cfg.default_period == "01D"
        assert cfg.default_content == "AA"

    def test_custom_defaults(self):
        cfg = SiteNamingConfig(
            site_id=testing.OTHER_SITE_ID,
            agency=testing.OTHER_AGENCY,
            default_sampling="01S",
            default_period="15M",
            default_content="MO",
        )
        assert cfg.default_sampling == "01S"
        assert cfg.default_period == "15M"
        assert cfg.default_content == "MO"

    def test_invalid_site_id(self):
        with pytest.raises(ValidationError):
            SiteNamingConfig(site_id="FANX", agency=testing.AGENCY)

    def test_invalid_agency(self):
        with pytest.raises(ValidationError):
            SiteNamingConfig(site_id=testing.SITE_ID, agency="TU")

    def test_invalid_sampling(self):
        with pytest.raises(ValidationError):
            SiteNamingConfig(
                site_id=testing.SITE_ID, agency=testing.AGENCY, default_sampling="XY"
            )

    def test_from_dict(self):
        d = {
            "site_id": testing.SITE_ID,
            "agency": testing.AGENCY,
            "default_sampling": "05S",
        }
        cfg = SiteNamingConfig.model_validate(d)
        assert cfg.site_id == testing.SITE_ID


class TestReceiverNamingConfig:
    def test_minimal(self):
        cfg = ReceiverNamingConfig(receiver_number=1)
        assert cfg.receiver_number == 1
        assert cfg.source_pattern == "auto"
        assert cfg.directory_layout == DirectoryLayout.YYDDD_SUBDIRS
        assert cfg.agency is None
        assert cfg.sampling is None

    def test_full(self):
        cfg = ReceiverNamingConfig(
            receiver_number=2,
            source_pattern="septentrio_sbf",
            directory_layout=DirectoryLayout.FLAT,
            agency=testing.OTHER_AGENCY,
            sampling="01S",
            period="15M",
            content="MO",
        )
        assert cfg.receiver_number == 2
        assert cfg.source_pattern == "septentrio_sbf"
        assert cfg.directory_layout == DirectoryLayout.FLAT

    def test_receiver_number_bounds(self):
        with pytest.raises(ValidationError):
            ReceiverNamingConfig(receiver_number=0)
        with pytest.raises(ValidationError):
            ReceiverNamingConfig(receiver_number=100)

    def test_from_dict(self):
        d = {
            "receiver_number": 1,
            "source_pattern": "auto",
            "directory_layout": "yyddd_subdirs",
        }
        cfg = ReceiverNamingConfig.model_validate(d)
        assert cfg.directory_layout == DirectoryLayout.YYDDD_SUBDIRS


class TestDirectoryLayout:
    def test_values(self):
        assert DirectoryLayout.YYDDD_SUBDIRS.value == "yyddd_subdirs"
        assert DirectoryLayout.YYYYDDD_SUBDIRS.value == "yyyyddd_subdirs"
        assert DirectoryLayout.FLAT.value == "flat"

    def test_from_string(self):
        assert DirectoryLayout("flat") == DirectoryLayout.FLAT
