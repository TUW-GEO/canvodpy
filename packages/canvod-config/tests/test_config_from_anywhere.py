#!/usr/bin/env python3
"""Test config loader works from any directory."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from canvod.config import loader as loader_module


def find_monorepo_root(start_path: Path) -> Path:
    """Find monorepo root by looking for a ``.git`` entry.

    Same rule as ``canvod.config.loader.find_monorepo_root``: a ``.git``
    directory (clone) or file (worktree/submodule). A ``pyproject.toml``
    would stop at the first workspace package instead of the repo root.
    """
    current = start_path
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find monorepo root")


# Find monorepo and check if the checkout has its own config
# (``canvodpy config init`` writes config/canvod-settings.yaml; gitignored)
MONOREPO_ROOT = find_monorepo_root(Path(__file__).parent)
CONFIG_DIR = MONOREPO_ROOT / "config"
HAS_CONFIG = (CONFIG_DIR / "canvod-settings.yaml").exists()

# Test directories (relative to monorepo root)
TEST_DIRS = [
    ".",
    "canvodpy",
    "packages/canvod-readers",
    "packages/canvod-readers/tests",
    "packages/canvod-utils/src/canvod/utils/config",
]


@pytest.mark.skipif(not HAS_CONFIG, reason="Integration test requires config files")
@pytest.mark.parametrize("test_dir", TEST_DIRS)
def test_config_loader_from_directory(test_dir: str):
    """Test that config loader works from various directories in monorepo."""
    full_path = MONOREPO_ROOT / test_dir

    # Skip if directory doesn't exist
    if not full_path.exists():
        pytest.skip(f"Directory doesn't exist: {test_dir}")

    # Sites configured in the checkout's config, as the expected output
    expected_sites = sorted(
        loader_module.ConfigLoader(CONFIG_DIR).load().sites.sites.keys()
    )

    # Test loading config from this directory, with the current interpreter
    # and without an env override, so the loader must discover config/ itself
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CANVOD_CONFIG_DIR", "CANVOD_CONFIG_FILE")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from canvod.config import load_config; "
            "config = load_config(); "
            "print(f'Sites: {sorted(config.sites.sites.keys())}')",
        ],
        cwd=full_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Verify it worked
    assert result.returncode == 0, (
        f"Config loading failed from {test_dir}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    # Verify the checkout's own config was found
    assert f"Sites: {expected_sites}" in result.stdout, (
        f"Expected sites {expected_sites} from {test_dir}\nGot: {result.stdout}"
    )


class TestFindMonorepoRoot:
    """The root is found from the working directory only."""

    def test_finds_the_checkout_from_inside_it(self, monkeypatch):
        monkeypatch.chdir(MONOREPO_ROOT / "packages" / "canvod-config")
        assert loader_module.find_monorepo_root() == MONOREPO_ROOT

    def test_raises_outside_any_checkout(self, tmp_path, monkeypatch):
        """No guess from where loader.py is installed (a wheel, another project)."""
        if any((p / ".git").exists() for p in [tmp_path, *tmp_path.parents]):
            pytest.skip("the temporary directory lies inside a git checkout")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match=r"no \.git entry"):
            loader_module.find_monorepo_root()


class TestGetTemplateDir:
    """Templates ship as real package data — always reachable, no search needed."""

    def test_template_dir_exists_and_has_expected_files(self):
        template_dir = loader_module.get_template_dir()
        assert template_dir.exists()
        assert (template_dir / "canvod-settings.yaml.example").exists()

    def test_template_dir_independent_of_monorepo_lookup(self):
        """Even if monorepo-root discovery fails, templates are still found."""
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            template_dir = loader_module.get_template_dir()
            assert template_dir.exists()

    def test_settings_template_sets_no_deprecated_storage_key(self):
        """A config copied from the template must not warn on every run."""
        import yaml

        text = (
            loader_module.get_template_dir() / "canvod-settings.yaml.example"
        ).read_text()
        storage = yaml.safe_load(text)["processing"]["storage"]
        assert "vod_store_strategy" not in storage


class TestGetDefaultConfigDir:
    """XDG-first default, with dev-checkout convenience when available."""

    @pytest.fixture(autouse=True)
    def _no_env_override(self, monkeypatch):
        monkeypatch.delenv("CANVOD_CONFIG_DIR", raising=False)

    def test_env_var_wins_over_the_checkout_config(self, tmp_path, monkeypatch):
        """CANVOD_CONFIG_DIR (also set by --config-dir) comes first."""
        fake_root = tmp_path / "checkout"
        (fake_root / "config").mkdir(parents=True)
        monkeypatch.setenv("CANVOD_CONFIG_DIR", str(tmp_path / "mine"))
        with patch.object(loader_module, "find_monorepo_root", return_value=fake_root):
            result = loader_module.get_default_config_dir()
        assert result == tmp_path / "mine"

    def test_falls_back_to_xdg_when_no_monorepo_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            result = loader_module.get_default_config_dir()
        assert result == tmp_path / "canvodpy"

    def test_falls_back_to_home_config_when_no_xdg_env(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        with patch.object(
            loader_module, "find_monorepo_root", side_effect=RuntimeError("no repo")
        ):
            result = loader_module.get_default_config_dir()
        assert result == Path.home() / ".config" / "canvodpy"

    def test_prefers_monorepo_config_dir_when_it_exists(self, tmp_path):
        """Dev-checkout convenience: an existing {monorepo_root}/config wins."""
        fake_root = tmp_path / "checkout"
        (fake_root / "config").mkdir(parents=True)
        with patch.object(loader_module, "find_monorepo_root", return_value=fake_root):
            result = loader_module.get_default_config_dir()
        assert result == fake_root / "config"

    def test_ignores_monorepo_root_without_config_dir(self, tmp_path, monkeypatch):
        """A .git found upward with no config/ dir still falls through to XDG."""
        fake_root = tmp_path / "checkout_no_config"
        fake_root.mkdir(parents=True)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        with patch.object(loader_module, "find_monorepo_root", return_value=fake_root):
            result = loader_module.get_default_config_dir()
        assert result == tmp_path / "xdg" / "canvodpy"


def _write_minimal_config(config_dir: Path, stores_root: Path) -> None:
    import yaml

    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "canvod-settings.yaml").write_text(
        yaml.safe_dump(
            {
                "processing": {
                    "metadata": {
                        "author": "A",
                        "email": "a@example.com",
                        "institution": "B",
                    },
                    "storage": {"stores_root_dir": str(stores_root)},
                },
                "sites": {},
            }
        )
    )


class TestLoadConfigEnvCaching:
    """Regression tests for the stale-cache bug fixed 2026-07-21.

    ``load_config()`` used to be the ``lru_cache``-wrapped function itself,
    resolving ``CANVOD_CONFIG_DIR``/``CANVOD_CONFIG_FILE`` from the
    environment *inside* the cached body. A bare ``load_config()`` call made
    before those env vars were set (e.g. ``canvodpy.logging.logging_config``'s
    module-level ``LOGGER = configure_logging()``, which called it at import
    time until 2026-10) would cache the pre-overlay config under the no-arg key -- and
    every later bare call in the same process, however much later, however
    many env vars had since been set, would silently get that stale config
    back. Confirmed against a real remote chunk-size sweep (dev/
    rechunk_sweep_remote.sh, 2026-07-20/21): every leg after the first wrote
    to the same store with the same chunk strategy, because the store-path
    and chunk-strategy resolution deep in canvod-store both go through bare
    ``load_config()`` calls.
    """

    def _clear(self):
        loader_module.load_config.cache_clear()

    def test_bare_call_after_env_var_set_picks_up_new_config_dir(
        self, tmp_path, monkeypatch
    ):
        self._clear()
        try:
            base_dir = tmp_path / "base"
            base_root = tmp_path / "base_store"
            _write_minimal_config(base_dir, base_root)
            monkeypatch.setenv("CANVOD_CONFIG_DIR", str(base_dir))

            # Simulate an early bare call before the "real" config dir is
            # known -- e.g. an import-time side effect elsewhere.
            early = loader_module.load_config()
            assert early.processing.storage.stores_root_dir == base_root

            # A different config dir becomes active later in the same
            # process (e.g. a test fixture, or a CLI overlay env var).
            other_dir = tmp_path / "other"
            other_root = tmp_path / "other_store"
            _write_minimal_config(other_dir, other_root)
            monkeypatch.setenv("CANVOD_CONFIG_DIR", str(other_dir))

            # A later bare call, with no args, must reflect the *current*
            # environment, not whatever was cached from the first call.
            later = loader_module.load_config()
            assert later.processing.storage.stores_root_dir == other_root
        finally:
            self._clear()

    def test_bare_call_after_overlay_env_var_set_picks_up_overlay(
        self, tmp_path, monkeypatch
    ):
        self._clear()
        try:
            config_dir = tmp_path / "config"
            base_root = tmp_path / "base_store"
            _write_minimal_config(config_dir, base_root)
            monkeypatch.setenv("CANVOD_CONFIG_DIR", str(config_dir))
            monkeypatch.delenv("CANVOD_CONFIG_FILE", raising=False)

            # Early bare call, no overlay active yet.
            early = loader_module.load_config()
            assert early.processing.storage.stores_root_dir == base_root

            # An overlay becomes active (mirrors cli/run.py's `--config`
            # handling: it sets CANVOD_CONFIG_FILE in os.environ, then
            # calls load_config(config_file=...) explicitly).
            overlay_root = tmp_path / "overlay_store"
            overlay_path = tmp_path / "overlay.yaml"
            overlay_path.write_text(
                f"processing:\n  storage:\n    stores_root_dir: {overlay_root}\n"
            )
            monkeypatch.setenv("CANVOD_CONFIG_FILE", str(overlay_path))
            explicit = loader_module.load_config(config_file=overlay_path)
            assert explicit.processing.storage.stores_root_dir == overlay_root

            # A bare call elsewhere in the same process, after the overlay
            # env var was set, must also see the overlay -- not the config
            # cached by the first bare call above.
            later = loader_module.load_config()
            assert later.processing.storage.stores_root_dir == overlay_root
        finally:
            self._clear()

    def test_cache_clear_is_still_exposed_on_the_public_function(self):
        """`load_config` is now a thin wrapper, not the lru_cache object
        itself -- `.cache_clear()`/`.cache_info()` must still work, since
        callers (e.g. canvodpy/tests/test_cli_store.py) rely on them."""
        assert hasattr(loader_module.load_config, "cache_clear")
        assert hasattr(loader_module.load_config, "cache_info")
        loader_module.load_config.cache_clear()
        info = loader_module.load_config.cache_info()
        assert info.currsize == 0


class TestFormatValidationError:
    """format_validation_error() turns a ConfigValidationError into
    actionable, human-readable text — no Pydantic internals, no traceback."""

    def _make_error(self, config_dir: Path) -> loader_module.ConfigValidationError:
        from pydantic import ValidationError

        from canvod.config.models import ProcessingConfig

        try:
            ProcessingConfig(
                metadata={
                    "author": "Your Name",
                    "email": "your.email@example.com",
                    "institution": "X",
                },
                storage={"stores_root_dir": str(config_dir)},
            )
        except ValidationError as e:
            return loader_module.ConfigValidationError(e, config_dir)
        raise AssertionError("expected ProcessingConfig to reject placeholder values")

    def test_leads_with_dotted_field_path(self, tmp_path):
        error = self._make_error(tmp_path)
        formatted = loader_module.format_validation_error(error)
        assert "metadata.author" in formatted
        assert "metadata.email" in formatted

    def test_strips_value_error_prefix_and_pydantic_url(self, tmp_path):
        error = self._make_error(tmp_path)
        formatted = loader_module.format_validation_error(error)
        assert "Value error," not in formatted
        assert "errors.pydantic.dev" not in formatted

    def test_names_the_actual_settings_file(self, tmp_path):
        error = self._make_error(tmp_path)
        formatted = loader_module.format_validation_error(error)
        assert str(tmp_path / "canvod-settings.yaml") in formatted

    def test_preserves_the_custom_validator_message(self, tmp_path):
        error = self._make_error(tmp_path)
        formatted = loader_module.format_validation_error(error)
        assert "fill in your real name" in formatted
        assert "fill in your real email" in formatted


if __name__ == "__main__":
    """Allow running as script for manual testing."""
    if not HAS_CONFIG:
        print("⚠️  Skipping: Config files not found")
        exit(0)

    print("=" * 70)
    print("Testing config loader from multiple directories")
    print("=" * 70)

    failed = []
    for test_dir in TEST_DIRS:
        full_path = MONOREPO_ROOT / test_dir
        if not full_path.exists():
            print(f"\n📁 Testing from: {test_dir}")
            print("   ⏭️  SKIPPED (directory doesn't exist)")
            continue

        print(f"\n📁 Testing from: {test_dir}")

        try:
            test_config_loader_from_directory(test_dir)
            print("   ✅ SUCCESS")
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            failed.append(test_dir)

    print("\n" + "=" * 70)
    if failed:
        print(f"❌ FAILED: {len(failed)}/{len(TEST_DIRS)} directories")
        for d in failed:
            print(f"   - {d}")
    else:
        print(f"✅ SUCCESS: All {len(TEST_DIRS)} directories passed!")
    print("=" * 70)
