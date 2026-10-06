"""Base abstractions for preprocessing operations."""

import importlib.metadata
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

import xarray as xr


def software_versions(packages: Iterable[str]) -> dict[str, str]:
    """Installed version of each package, recorded with every preprocessing.

    Parameters
    ----------
    packages : Iterable[str]
        Distribution names, e.g. ``["canvod-ops", "canvod-grids"]``.
    """
    return {name: importlib.metadata.version(name) for name in sorted(set(packages))}


@dataclass(frozen=True)
class OpResult:
    """Immutable record of a single preprocessing operation."""

    op_name: str
    parameters: dict[str, Any]
    input_shape: dict[str, int]
    output_shape: dict[str, int]
    duration_seconds: float
    notes: str = ""
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def step(self) -> dict[str, Any]:
        """This operation's entry in the preprocessing record.

        ``settings`` are the configured parameters, ``result`` what the
        operation measured or derived (see
        ``canvod.config.models.preprocessing_record``).
        """
        return {"op": self.op_name, "settings": self.parameters, "result": self.result}


class Op(ABC):
    """Abstract base class for a preprocessing operation.

    Each ``Op`` is a callable carrying config set at construction time.
    At call time it is a pure ``Dataset -> (Dataset, OpResult)`` transform.
    """

    #: Packages whose code the operation runs; their versions go into the
    #: preprocessing record.
    packages: ClassVar[tuple[str, ...]] = ("canvod-ops",)

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def settings(self) -> dict[str, Any]:
        """The configured parameters, as the preprocessing record holds them.

        Known before the operation runs, so a run can compare them with the
        records of a store before it processes any data.
        """

    @abstractmethod
    def __call__(self, ds: xr.Dataset) -> tuple[xr.Dataset, OpResult]: ...
