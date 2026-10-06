"""Preprocessing pipeline configuration: temporal aggregation, grid assignment, statistics."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import Field, field_validator

from .base import _StrictModel

_FREQ_UNIT_SECONDS = {"s": 1, "min": 60, "h": 3600}
_FREQ = re.compile(r"^([1-9][0-9]*)(s|min|h)$")


class TemporalAggregationConfig(_StrictModel):
    """Temporal aggregation of the observations into time bins."""

    enabled: bool = Field(True, description="Apply the temporal aggregation")
    freq: str = Field(
        ...,
        description=(
            "Bin length: a whole number of seconds, minutes or hours "
            "('30s', '1min', '1h') that divides one day"
        ),
    )
    method: Literal["mean", "median"] = Field(
        ...,
        description="Statistic of the floating-point observations in each bin",
    )
    integer_method: Literal["first", "last", "middle"] = Field(
        ...,
        description=(
            "Value of each bin integer variables (flags and codes such as LLI "
            "and SSI) take, in time order; they cannot be combined"
        ),
    )

    @field_validator("freq")
    @classmethod
    def _freq_divides_day(cls, value: str) -> str:
        match = _FREQ.match(value)
        if match is None:
            msg = (
                f"freq must be a whole number followed by 's', 'min' or 'h' "
                f"(e.g. '30s', '1min'), not {value!r}"
            )
            raise ValueError(msg)
        seconds = int(match.group(1)) * _FREQ_UNIT_SECONDS[match.group(2)]
        if 86_400 % seconds:
            msg = (
                f"freq {value!r} does not divide one day, so the bins would "
                "not start at 00:00 of every day"
            )
            raise ValueError(msg)
        return value


class GridAssignmentConfig(_StrictModel):
    """Assignment of each observation to a cell of a hemispherical grid."""

    enabled: bool = Field(True, description="Apply the grid cell assignment")
    grid_type: str = Field(..., description="Grid type, e.g. 'equal_area'")
    angular_resolution: float = Field(
        ..., gt=0, le=90, description="Angular resolution in degrees"
    )


class HistogramBinsConfig(_StrictModel):
    """Custom histogram bin specification for a variable."""

    low: float = Field(..., description="Lower edge of the first bin")
    high: float = Field(..., description="Upper edge of the last bin")
    n_bins: int = Field(..., ge=1, description="Number of bins")


class StatisticsConfig(_StrictModel):
    """Streaming statistics configuration.

    Reserved for a future release: no run reads this section yet, so setting
    it has no effect.
    """

    enabled: bool = Field(False, description="Enable streaming statistics collection")
    variables: list[str] = Field(
        default_factory=lambda: ["SNR"],
        description="Variables to profile",
    )
    gk_epsilon: float = Field(
        0.01, gt=0, lt=1, description="GK sketch approximation parameter"
    )
    quantile_probs: list[float] = Field(
        default_factory=lambda: [
            0.001,
            0.01,
            0.05,
            0.1,
            0.25,
            0.5,
            0.75,
            0.9,
            0.95,
            0.99,
            0.999,
        ],
        description="Quantile probabilities to compute",
    )
    custom_histogram_bins: dict[str, HistogramBinsConfig] = Field(
        default_factory=dict,
        description="Per-variable histogram bin overrides",
    )


class PreprocessingConfig(_StrictModel):
    """Operations applied before the data are written to the GNSS store.

    Each operation is applied only if its section is set (and ``enabled``).
    Temporal aggregation runs first, then the grid cell assignment.
    """

    temporal_aggregation: TemporalAggregationConfig | None = Field(
        None, description="Temporal aggregation; not applied unless set"
    )
    grid_assignment: GridAssignmentConfig | None = Field(
        None, description="Grid cell assignment; not applied unless set"
    )
    statistics: StatisticsConfig = Field(
        default_factory=StatisticsConfig,
        description="Streaming statistics; reserved, not read by any run yet",
    )


#: Version of the layout of the preprocessing record (:func:`preprocessing_record`);
#: changes only when the layout changes, independently of the software version.
#: Format 1 named one version, ``canvod_ops_version``; format 2 names the
#: version of every package whose code ran, under ``software``.
PREPROCESSING_RECORD_VERSION = 2

#: Record formats this version reads; the steps have the same layout in all.
_READABLE_RECORD_VERSIONS = (1, 2)

#: Key under which a dataset carries its preprocessing record in memory, from
#: the preprocessing to the store write. The stores never write it into the
#: data: they move it into the ``preprocessing`` column of their log book.
PREPROCESSING_ATTR = "Preprocessing"


class PreprocessingMismatchError(Exception):
    """Data preprocessed differently from the data they would be stored with.

    Deliberately not a ``ValueError``: a run stops on it instead of skipping
    the receiver-day, because every later day would be refused the same way.
    """


def preprocessing_record(steps: list[dict[str, Any]], software: dict[str, str]) -> str:
    """JSON record of the preprocessing applied to a dataset.

    Parameters
    ----------
    steps : list[dict]
        One ``{"op", "settings", "result"}`` mapping per operation, in the
        order they ran (see ``canvod.ops.OpResult.step``). ``settings`` are
        the configured values, ``result`` what the operation measured or
        derived (e.g. the input sampling). An empty list records that no
        preprocessing was applied.
    software : dict[str, str]
        Version of each package whose code ran the operations, e.g.
        ``{"canvod-grids": "1.0.3", "canvod-ops": "1.2.0"}``.

    Returns
    -------
    str
        ``{"format_version", "software", "steps"}`` as sorted-key JSON.
        ``format_version`` is the version of this record's layout, not of
        the software.
    """
    return json.dumps(
        {
            "format_version": PREPROCESSING_RECORD_VERSION,
            "software": software,
            "steps": steps,
        },
        sort_keys=True,
    )


def preprocessing_steps(record: str) -> list[dict[str, Any]]:
    """Steps of a record; ``""`` (no record) gives no steps.

    Log-book rows written before the record existed hold ``""``; no
    preprocessing was applied by canVODpy then.

    Raises
    ------
    ValueError
        If the record has an unknown format version.
    """
    if not record:
        return []
    parsed = json.loads(record)
    version = parsed.get("format_version")
    if version not in _READABLE_RECORD_VERSIONS:
        msg = (
            f"Preprocessing record format {version!r} is not supported "
            f"(this canVODpy reads formats {_READABLE_RECORD_VERSIONS})"
        )
        raise ValueError(msg)
    return list(parsed["steps"])


def preprocessing_settings(record: str) -> list[dict[str, Any]]:
    """The operations and settings of a record, without their results.

    Two datasets may be stored together if and only if these are equal; the
    results (e.g. the measured input sampling) may differ.
    """
    return [
        {"op": step["op"], "settings": step["settings"]}
        for step in preprocessing_steps(record)
    ]


def describe_settings(settings: list[dict[str, Any]]) -> str:
    """Short text of operations and settings, e.g. for a store history entry.

    ``settings`` as :func:`preprocessing_settings` returns them; no
    operations give ``"none"``.
    """
    if not settings:
        return "none"
    return ", ".join(
        f"{step['op']}("
        + ", ".join(f"{k}={v}" for k, v in sorted(step["settings"].items()))
        + ")"
        for step in settings
    )


def describe_preprocessing(record: str) -> str:
    """Short text of a record's operations and settings."""
    return describe_settings(preprocessing_settings(record))


def vod_preprocessing_record(sources: dict[str, list[str]]) -> str:
    """Record of a VOD result: the records of the GNSS data behind it.

    Parameters
    ----------
    sources : dict[str, list[str]]
        Per receiver, the preprocessing records of the GNSS data the result
        was computed from (usually one; several if the data span days with
        different results, e.g. another input sampling).

    Returns
    -------
    str
        ``sources`` as sorted-key JSON.

    Raises
    ------
    PreprocessingMismatchError
        If the receivers' data were preprocessed with different operations
        or settings: their VOD would compare unlike observations.
    """
    distinct = {
        json.dumps(preprocessing_settings(record), sort_keys=True): record
        for records in sources.values()
        for record in records
    }
    if len(distinct) > 1:
        described = "; ".join(
            f"{name}: " + " | ".join(describe_preprocessing(r) for r in records)
            for name, records in sources.items()
        )
        msg = (
            "The receivers of a VOD analysis must be preprocessed the same "
            f"way, but their GNSS data have: {described}"
        )
        raise PreprocessingMismatchError(msg)
    return json.dumps(sources, sort_keys=True)


def vod_preprocessing_settings(record: str) -> list[dict[str, Any]]:
    """Operations and settings behind a VOD result (see
    :func:`vod_preprocessing_record`); ``""`` gives none."""
    if not record:
        return []
    for records in json.loads(record).values():
        for gnss_record in records:
            return preprocessing_settings(gnss_record)
    return []


def split_preprocessing(attrs: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Separate the in-memory record from the other dataset attributes.

    Returns
    -------
    tuple[dict, str]
        The attributes without :data:`PREPROCESSING_ATTR`, and the record
        (``""`` if the dataset carries none).
    """
    rest = {k: v for k, v in attrs.items() if k != PREPROCESSING_ATTR}
    return rest, str(attrs.get(PREPROCESSING_ATTR, ""))
