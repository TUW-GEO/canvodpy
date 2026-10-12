"""Reader and VOD calculator plugins from installed packages (entry points)."""

from __future__ import annotations

import textwrap
from importlib.metadata import EntryPoint

import pytest
from canvodpy.factories import ReaderFactory, VODFactory, register_plugins
from canvodpy.orchestrator.discovery import _file_types
from pydantic import ValidationError

from canvod.config.models.sites import ReceiverConfig
from canvod.preflight.convention import CanVODFilename
from canvod.utils import plugins
from canvod.utils.plugins import READER_GROUP, VOD_CALCULATOR_GROUP, PluginError

_PLUGIN_MODULE = """
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import ClassVar

import xarray as xr
from canvod.readers.base import GNSSDataReader
from canvod.vod.calculator import VODCalculator


class MyFormatReader(GNSSDataReader):
    file_type: ClassVar[str] = "myf"

    @property
    def source_format(self) -> str:
        return "my_format"

    @property
    def file_hash(self) -> str:
        return "0123456789abcdef"

    def to_ds(self, keep_data_vars=None, **kwargs) -> xr.Dataset:
        raise NotImplementedError

    def iter_epochs(self) -> Iterator[object]:
        return iter([])

    @property
    def start_time(self) -> datetime:
        return datetime(2025, 1, 1, tzinfo=UTC)

    @property
    def end_time(self) -> datetime:
        return datetime(2025, 1, 2, tzinfo=UTC)

    @property
    def systems(self) -> list[str]:
        return ["G"]

    @property
    def num_satellites(self) -> int:
        return 1


class NoFileType(MyFormatReader):
    file_type: ClassVar[str] = "Not A Type"


class MyCalculator(VODCalculator):
    def calculate_vod(self) -> xr.Dataset:
        raise NotImplementedError


class NotACalculator:
    pass


NOT_A_CLASS = 1
"""


@pytest.fixture
def installed(monkeypatch, tmp_path):
    """Install fake plugin entry points: ``installed(group, name, value)``."""
    (tmp_path / "my_plugin.py").write_text(textwrap.dedent(_PLUGIN_MODULE))
    monkeypatch.syspath_prepend(str(tmp_path))
    eps: list[EntryPoint] = []
    monkeypatch.setattr(
        plugins,
        "entry_points",
        lambda group: [ep for ep in eps if ep.group == group],
    )
    plugins.load_plugins.cache_clear()
    before = {f: dict(f._registry) for f in (ReaderFactory, VODFactory)}

    def install(group: str, name: str, value: str) -> None:
        eps.append(EntryPoint(name=name, value=value, group=group))
        plugins.load_plugins.cache_clear()

    yield install

    plugins.load_plugins.cache_clear()
    for factory, registry in before.items():
        factory._registry.clear()
        factory._registry.update(registry)


def test_reader_plugin_reaches_the_run(installed) -> None:
    installed(READER_GROUP, "my_format", "my_plugin:MyFormatReader")
    register_plugins()

    assert ReaderFactory.component_class("my_format").__name__ == "MyFormatReader"
    assert _file_types("my_format") == frozenset({"myf"})
    name = CanVODFilename.from_filename("FANR01INK_R_20250010000_01D_05S_AA.myf")
    assert name.file_type == "myf"
    rx = ReceiverConfig(type="canopy", directory="x", reader_format="my_format")
    assert rx.reader_format == "my_format"


def test_auto_never_picks_a_plugin(installed) -> None:
    installed(READER_GROUP, "my_format", "my_plugin:MyFormatReader")
    register_plugins()

    assert "myf" not in _file_types(None)
    assert "myf" not in _file_types("auto")


def test_vod_calculator_plugin_registers(installed) -> None:
    installed(VOD_CALCULATOR_GROUP, "my_model", "my_plugin:MyCalculator")
    register_plugins()

    assert "my_model" in VODFactory.list_available()


def test_unknown_reader_format_is_refused() -> None:
    with pytest.raises(ValidationError, match="Unknown reader_format 'my_format'"):
        ReceiverConfig(type="canopy", directory="x", reader_format="my_format")


def test_unknown_file_type_is_not_canonical() -> None:
    with pytest.raises(ValueError, match="Unknown file type 'myf'"):
        CanVODFilename.from_filename("FANR01INK_R_20250010000_01D_05S_AA.myf")


@pytest.mark.parametrize(
    ("group", "name", "value", "message"),
    [
        (READER_GROUP, "rinex3", "my_plugin:MyFormatReader", "built-in"),
        (READER_GROUP, "auto", "my_plugin:MyFormatReader", "built-in"),
        (VOD_CALCULATOR_GROUP, "tau_omega", "my_plugin:MyCalculator", "built-in"),
        (READER_GROUP, "bad", "my_plugin:MyCalculator", "must inherit"),
        (VOD_CALCULATOR_GROUP, "bad", "my_plugin:NotACalculator", "must inherit"),
        (READER_GROUP, "bad", "my_plugin:NoFileType", "no valid file_type"),
        (READER_GROUP, "bad", "no_such_module:Reader", "cannot be imported"),
        (READER_GROUP, "bad", "my_plugin:EPOCH", "cannot be imported"),
        (READER_GROUP, "bad", "my_plugin:NOT_A_CLASS", "not a class"),
    ],
)
def test_broken_plugin_fails_loudly(installed, group, name, value, message) -> None:
    installed(group, name, value)
    with pytest.raises(PluginError, match=message):
        register_plugins()


def test_a_name_declared_twice_fails(installed) -> None:
    installed(READER_GROUP, "my_format", "my_plugin:MyFormatReader")
    installed(READER_GROUP, "my_format", "my_plugin:NoFileType")
    with pytest.raises(PluginError, match="Two installed packages"):
        register_plugins()


def test_plugin_error_names_the_package(installed) -> None:
    """Without package metadata (as here) the entry point value stands in."""
    installed(READER_GROUP, "bad", "no_such_module:Reader")
    with pytest.raises(PluginError, match="no_such_module:Reader"):
        register_plugins()
