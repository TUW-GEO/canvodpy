"""Restoring the environment a store was written with (``show.extract_env``)."""

import hashlib

from canvod.store_metadata import show
from canvod.store_metadata.schema import Environment
from canvod.store_metadata.testing import made_up_metadata

_LOCK = 'version = 1\n\n[[package]]\nname = "fangorn"\n'
_PYPROJECT = '[project]\nname = "fangorn"\n'


def _metadata_with_environment():
    meta = made_up_metadata()
    meta.environment = Environment(
        uv_lock_hash=hashlib.sha256(_LOCK.encode()).hexdigest(),
        uv_lock_text=_LOCK,
        pyproject_toml_text=_PYPROJECT,
    )
    return meta


class TestExtractEnv:
    def test_restored_files_are_the_stored_bytes(self, tmp_path, monkeypatch):
        """No newline translation: on Windows, text mode writes \\r\\n."""
        meta = _metadata_with_environment()
        monkeypatch.setattr(show, "read_metadata", lambda *_args: meta)

        out = show.extract_env(tmp_path / "store", tmp_path / "env")

        assert (out / "uv.lock").read_bytes() == _LOCK.encode()
        assert (out / "pyproject.toml").read_bytes() == _PYPROJECT.encode()

    def test_restored_lock_matches_the_recorded_hash(self, tmp_path, monkeypatch):
        meta = _metadata_with_environment()
        monkeypatch.setattr(show, "read_metadata", lambda *_args: meta)

        out = show.extract_env(tmp_path / "store", tmp_path / "env")

        digest = hashlib.sha256((out / "uv.lock").read_bytes()).hexdigest()
        assert digest == meta.environment.uv_lock_hash
