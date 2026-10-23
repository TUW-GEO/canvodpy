"""Tests for ConfigLoader round-trip and merge logic."""

from pathlib import Path

import pytest
import yaml

from canvod.config.loader import ConfigLoader, ConfigValidationError


class TestDeepMerge:
    """Test _deep_merge logic."""

    def test_flat_override(self):
        """Override values replace base values."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = loader._deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        """Nested dicts are merged recursively."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 99, "c": 3}}
        result = loader._deep_merge(base, override)
        assert result == {"outer": {"a": 1, "b": 99, "c": 3}}

    def test_override_adds_new_keys(self):
        """New keys in override are added to result."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"x": 1}
        override = {"y": 2}
        result = loader._deep_merge(base, override)
        assert result == {"x": 1, "y": 2}

    def test_override_replaces_non_dict_with_dict(self):
        """Non-dict value replaced by dict from override."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"key": "string"}
        override = {"key": {"nested": True}}
        result = loader._deep_merge(base, override)
        assert result == {"key": {"nested": True}}

    def test_base_unchanged(self):
        """Original base dict is not mutated."""
        loader = ConfigLoader(config_dir=Path("/unused"))
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"c": 99}}
        loader._deep_merge(base, override)
        assert base == {"a": 1, "b": {"c": 2}}


class TestConfigLoaderRoundTrip:
    """Test ConfigLoader with temporary YAML files."""

    def _write_yaml(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            yaml.dump(data, f)

    def test_load_from_temp_config_dir(self, tmp_path):
        """A unified canvod-settings.yaml should load into CanvodConfig."""
        self._write_yaml(
            tmp_path / "canvod-settings.yaml",
            {
                "processing": {
                    "metadata": {
                        "author": "Test Author",
                        "email": "test@example.com",
                        "institution": "Test University",
                    },
                    "storage": {
                        "stores_root_dir": str(tmp_path / "stores"),
                    },
                },
                "sites": {
                    "TestSite": {
                        "gnss_site_data_root": str(tmp_path / "data"),
                        "receivers": {
                            "canopy_01": {
                                "type": "canopy",
                                "directory": "canopy",
                            },
                            "reference_01": {
                                "type": "reference",
                                "directory": "reference",
                                "paired_canopies": "all",
                            },
                        },
                    }
                },
                "sids": {"mode": "all"},
            },
        )

        loader = ConfigLoader(config_dir=tmp_path)
        config = loader.load()

        assert config.processing.metadata.author == "Test Author"
        assert config.processing.metadata.email == "test@example.com"
        assert "TestSite" in config.sites.sites
        assert config.sids.mode == "all"

    def test_user_config_overrides_defaults(self, tmp_path):
        """User canvod-settings.yaml should override default values."""
        self._write_yaml(
            tmp_path / "canvod-settings.yaml",
            {
                "processing": {
                    "metadata": {
                        "author": "Custom Author",
                        "email": "custom@example.com",
                        "institution": "Custom Univ",
                    },
                    "aux_data": {"agency": "GFZ"},
                    "storage": {
                        "stores_root_dir": str(tmp_path / "stores"),
                    },
                },
                "sites": {},
                "sids": {"mode": "all"},
            },
        )

        config = ConfigLoader(config_dir=tmp_path).load()

        # User value should override default
        assert config.processing.aux_data.agency == "GFZ"
        # Default values should still be present
        assert config.processing.netcdf_compression.zlib is True


class TestConfigLoaderDefaults:
    """Test the single-required-file design and fallback to package defaults
    for sections a user's canvod-settings.yaml omits."""

    def _write_yaml(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            yaml.dump(data, f)

    def test_missing_settings_file_raises_file_not_found(self, tmp_path):
        """canvod-settings.yaml must exist — ConfigLoader no longer defaults
        silently when the whole file is absent (see loader.py's load())."""
        loader = ConfigLoader(config_dir=tmp_path)
        with pytest.raises(FileNotFoundError, match=r"canvod-settings\.yaml"):
            loader.load()

    def test_omitted_sections_use_package_defaults(self, tmp_path):
        """Sections omitted from canvod-settings.yaml fall back to package
        defaults (metadata must still be supplied — package defaults for
        author/email are rejected sentinel placeholders by design)."""
        self._write_yaml(
            tmp_path / "canvod-settings.yaml",
            {
                "processing": {
                    "metadata": {
                        "author": "Test Author",
                        "email": "test@example.com",
                        "institution": "Test University",
                    },
                    "storage": {"stores_root_dir": str(tmp_path / "stores")},
                },
            },
        )
        loader = ConfigLoader(config_dir=tmp_path)
        config = loader.load()

        # aux_data and sids weren't specified — package defaults apply
        assert config.processing.aux_data.agency == "COD"
        assert config.sids.mode == "preset"
        assert config.sids.preset == "default"
        assert len(config.sids.get_sids()) == 271


class TestPreprocessingSetting:
    """``processing.preprocessing``: applied only if set, never by default."""

    def _write_settings(self, tmp_path: Path, extra: dict) -> None:
        processing = {
            "metadata": {
                "author": "Test Author",
                "email": "test@example.com",
                "institution": "Test University",
            },
            "storage": {"stores_root_dir": str(tmp_path / "stores")},
            **extra,
        }
        with open(tmp_path / "canvod-settings.yaml", "w") as f:
            yaml.dump({"processing": processing}, f)

    def test_not_set_by_default(self, tmp_path):
        self._write_settings(tmp_path, {})
        config = ConfigLoader(config_dir=tmp_path).load()
        assert config.processing.preprocessing is None

    def test_only_the_set_operation(self, tmp_path):
        self._write_settings(
            tmp_path,
            {
                "preprocessing": {
                    "temporal_aggregation": {
                        "freq": "1min",
                        "method": "median",
                        "integer_method": "first",
                    }
                }
            },
        )
        config = ConfigLoader(config_dir=tmp_path).load()
        preprocessing = config.processing.preprocessing
        assert preprocessing.temporal_aggregation.freq == "1min"
        assert preprocessing.temporal_aggregation.enabled
        assert preprocessing.grid_assignment is None

    @pytest.mark.parametrize(
        ("freq", "match"),
        [
            ("1T", "whole number followed by"),
            ("1.5min", "whole number followed by"),
            ("7min", "does not divide one day"),
        ],
    )
    def test_freq_must_divide_a_day(self, tmp_path, freq, match):
        self._write_settings(
            tmp_path,
            {
                "preprocessing": {
                    "temporal_aggregation": {
                        "freq": freq,
                        "method": "mean",
                        "integer_method": "first",
                    }
                }
            },
        )
        with pytest.raises(ConfigValidationError, match=match):
            ConfigLoader(config_dir=tmp_path).load()

    def test_method_is_required(self, tmp_path):
        self._write_settings(
            tmp_path, {"preprocessing": {"temporal_aggregation": {"freq": "1min"}}}
        )
        with pytest.raises(ConfigValidationError, match="method"):
            ConfigLoader(config_dir=tmp_path).load()

    def test_integer_method_is_required(self, tmp_path):
        self._write_settings(
            tmp_path,
            {
                "preprocessing": {
                    "temporal_aggregation": {"freq": "1min", "method": "mean"}
                }
            },
        )
        with pytest.raises(ConfigValidationError, match="integer_method"):
            ConfigLoader(config_dir=tmp_path).load()

    def test_integers_cannot_be_averaged(self, tmp_path):
        self._write_settings(
            tmp_path,
            {
                "preprocessing": {
                    "temporal_aggregation": {
                        "freq": "1min",
                        "method": "mean",
                        "integer_method": "mean",
                    }
                }
            },
        )
        with pytest.raises(ConfigValidationError, match="integer_method"):
            ConfigLoader(config_dir=tmp_path).load()


class TestConfigLoaderValidationError:
    """Test validation error handling."""

    def _write_yaml(self, path: Path, data: dict) -> None:
        with open(path, "w") as f:
            yaml.dump(data, f)

    def test_invalid_config_raises_config_validation_error(self, tmp_path):
        """Invalid config should raise ConfigValidationError (not sys.exit)."""
        self._write_yaml(
            tmp_path / "canvod-settings.yaml",
            {
                "processing": {
                    "metadata": {
                        "author": "Test",
                        "email": "test@example.com",
                        "institution": "Test",
                    },
                    "storage": {
                        "stores_root_dir": str(tmp_path),
                    },
                },
                "sites": {},
                # "mode" only accepts "all"/"preset"/"custom" — this is a
                # genuine Pydantic validation failure, not a mocked one.
                "sids": {"mode": "not_a_valid_mode"},
            },
        )

        loader = ConfigLoader(config_dir=tmp_path)

        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load()

        assert exc_info.value.config_dir == tmp_path
        assert isinstance(exc_info.value, ValueError)
