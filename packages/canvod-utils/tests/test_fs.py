"""Tests for the shared file-system helpers."""

from __future__ import annotations

import os
import types

from canvod.utils.tools import NEW_FILE_MODE, directory_size_bytes


def test_new_file_mode_is_the_mode_of_a_file_the_os_makes(tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.touch()
    assert plain.stat().st_mode & 0o777 == NEW_FILE_MODE


def test_directory_size_bytes_sums_the_files_recursively(tmp_path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 100)
    (tmp_path / "b").write_bytes(b"y" * 50)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c").write_bytes(b"z" * 25)
    assert directory_size_bytes(tmp_path) == 175


def test_directory_size_bytes_missing_path_is_zero(tmp_path) -> None:
    assert directory_size_bytes(tmp_path / "nope") == 0
    # A file, not a directory, is not a store folder to walk.
    file = tmp_path / "f"
    file.write_bytes(b"x")
    assert directory_size_bytes(file) == 0


def test_directory_size_bytes_does_not_follow_symlinks(tmp_path) -> None:
    (tmp_path / "real").write_bytes(b"x" * 10)
    (tmp_path / "link").symlink_to(tmp_path / "real")
    (tmp_path / "dir_real").mkdir()
    (tmp_path / "dir_real" / "in").write_bytes(b"y" * 10)
    (tmp_path / "dir_link").symlink_to(tmp_path / "dir_real", target_is_directory=True)
    # Neither the file symlink nor the directory symlink is followed.
    assert directory_size_bytes(tmp_path) == 20


class _FakeEntry:
    """A pretend ``os.DirEntry`` whose ``stat`` can fail mid-walk."""

    def __init__(self, name: str, size: int | None) -> None:
        self.path = str(name)  # a str, as a real DirEntry's path is
        self._name = name
        self._size = size

    def is_dir(self, follow_symlinks: bool = False) -> bool:
        return False

    def is_file(self, follow_symlinks: bool = False) -> bool:
        return True

    def stat(self, follow_symlinks: bool = False) -> types.SimpleNamespace:
        if self._size is None:
            raise FileNotFoundError(self._name)
        return types.SimpleNamespace(st_size=self._size)


class _FakeScandir:
    """A pretend ``os.scandir`` result: iterate and close like the real one."""

    def __init__(self, entries: list[_FakeEntry]) -> None:
        self._entries = entries

    def __iter__(self):
        return iter(self._entries)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def test_directory_size_bytes_skips_a_file_that_vanishes(monkeypatch, tmp_path) -> None:
    # A file removed between the listing and its stat ends the walk in the
    # published code; here the walk returns the size of the files left.
    monkeypatch.setattr(
        os,
        "scandir",
        lambda _path: _FakeScandir(
            [
                _FakeEntry("here.bin", size=100),
                _FakeEntry("gone.bin", size=None),
            ]
        ),
    )
    assert directory_size_bytes(tmp_path) == 100
