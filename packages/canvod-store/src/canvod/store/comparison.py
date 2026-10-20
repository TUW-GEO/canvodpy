"""Compare two Icechunk stores within fixed, science-based tolerances.

A public comparison for the reference-store check (spec #318, seam B) and
for comparing any two stores: a production store before and after an
upgrade, two runs, a rebuilt store against the reference. It only reads,
through :class:`~canvod.store.store.MyIcechunkStore` (``list_data_groups``,
``read_group`` and ``get_root_attrs``); it never changes how a store is
written or read.

The checks are xarray's own (:mod:`xarray.testing`): every variable and
coordinate of a group with ``assert_identical`` (values, dimensions and
attributes), the float variables of :data:`FLOAT_TOLERANCES` with
``assert_allclose`` within their tolerance. Before comparing, the
attributes that change with every run (:data:`VOLATILE_ATTRIBUTES`:
times, identifiers and the software version) are dropped from the store,
the groups and the variables; every other attribute must match.

The report lists, per group and variable, the kind of difference, the
number of differing values, the largest absolute difference and xarray's
message. It also lists groups, variables and coordinates present in one
store and not the other.

Tolerances are absolute and derive from the finest resolution any format
records. Every float tolerance follows from half the RINEX F14.3
resolution (0.001). See :data:`FLOAT_TOLERANCES` for the table and its
derivation, with the sources cited there (spec #318).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import numpy as np
import xarray as xr
from pydantic import BaseModel, Field, computed_field

from canvod.store.store import MyIcechunkStore

#: Absolute tolerances per variable, in the variable's unit. A float
#: variable not in this table is compared exactly and is reported as
#: "no tolerance set", so a new variable is noticed.
#:
#: Derivation, with the sources cited (spec #318):
#:
#: * ``SNR`` (and its 1-minute means), ``Pseudorange``, ``Phase``,
#:   ``Doppler``: 5e-4, in dB-Hz, m, cycles and Hz. Half the RINEX
#:   observation resolution, format F14.3 = 0.001 (RINEX 3.04,
#:   https://files.igs.org/pub/data/format/rinex304.pdf, observation
#:   record, p. 67; RINEX 2.11,
#:   https://files.igs.org/pub/data/format/rinex211.txt, observation
#:   record). SBF (0.25 dB-Hz) and NMEA GSV (1 dB-Hz) are
#:   coarser, so RINEX sets the limit.
#: * ``delta_snr`` (VOD store): 1e-3 dB. A difference of two SNR values
#:   carries two SNR errors, 2 * 5e-4.
#: * ``VOD``: 2e-4. dVOD =
#:   (ln 10 / 10) * 1e-3 = 2.3e-4, rounded down; see the formula in
#:   ``packages/canvod-vod/src/canvod/vod/calculator.py``.
#: * ``theta``, ``phi``: 1e-6 rad. Above the float32 spacing at pi/2
#:   (1.2e-7 rad), the precision theta and phi are stored with, so
#:   storage rounding never fails it; a larger difference is a changed
#:   satellite geometry.
FLOAT_TOLERANCES: dict[str, float] = {
    "SNR": 5e-4,
    "Pseudorange": 5e-4,
    "Phase": 5e-4,
    "Doppler": 5e-4,
    "delta_snr": 1e-3,
    "VOD": 2e-4,
    "theta": 1e-6,
    "phi": 1e-6,
}

#: The attributes dropped before comparing, because they change with every
#: run of the same code on the same data. A key is dropped wherever it
#: appears: in the store's root attributes, a group's attributes and a
#: variable's attributes, also inside a nested mapping.
VOLATILE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # Store attributes: times and identifiers of this run.
        "date_created",
        "date_modified",
        "canvod:uuid",
        "canvod:repository_metadata.identity.uuid",
        "canvod:repository_metadata.temporal.created",
        "canvod:repository_metadata.content_settings.set_at",
        "canvod:snapshot_summary.temporal.updated",
        # The software version that wrote the store.
        "canvod:repository_metadata.content_settings.canvodpy_version",
        "Software",
        # A hash of the GNSS store's values: values within the tolerances
        # change it, and the values themselves are compared.
        "canvod:repository_metadata.content_settings.gnss_content_hash",
    }
)
"""Attributes left out of the comparison, as dotted paths into nested
attributes. Two builds from the same code differ only in the times and
identifiers listed here; the version and the content hash change with
every release."""

# Lines of an xarray message kept in a report entry.
_MESSAGE_LINES = 12

_IDENTITY_COORDINATES = ("epoch", "sid")


class DiffKind(StrEnum):
    """The kind of a difference between two stores."""

    GROUP_MISSING = "group_missing"
    GROUP_EXTRA = "group_extra"
    VARIABLE_MISSING = "variable_missing"
    VARIABLE_EXTRA = "variable_extra"
    COORDINATE_MISSING = "coordinate_missing"
    COORDINATE_EXTRA = "coordinate_extra"
    DIMENSION = "dimension"
    COORDINATE_CHANGE = "coordinate_change"
    VALUE = "value"
    NO_TOLERANCE = "no_tolerance"
    ATTRIBUTE = "attribute"


class ComparisonDifference(BaseModel):
    """One difference between the two stores.

    ``group`` is the group name, or ``""`` for a store-level difference
    (a root attribute of the store). ``variable`` is the variable,
    coordinate, dimension or attribute name. ``n_values`` is the number
    of differing values (a value missing in one store only counts),
    ``largest_diff`` the largest absolute difference of the values present
    in both. ``detail`` is xarray's message or a short description.
    """

    group: str = ""
    kind: DiffKind
    variable: str | None = None
    n_values: int | None = None
    largest_diff: float | int | str | None = None
    tolerance: float | None = None
    detail: str | None = None


class StoreComparison(BaseModel):
    """The result of comparing two stores.

    ``matches`` is ``True`` when the two stores have the same groups and
    no difference was found. ``differences`` holds every difference;
    groups present in one store and not the other are listed separately.

    The JSON form (``model_dump_json``) is for CI; the text form
    (``to_text``) is for a person.
    """

    groups_in_reference: int
    groups_in_new: int
    groups_only_in_reference: list[str] = Field(default_factory=list)
    groups_only_in_new: list[str] = Field(default_factory=list)
    differences: list[ComparisonDifference] = Field(default_factory=list)

    @computed_field
    @property
    def matches(self) -> bool:
        """True when the stores match (no group and no value difference)."""
        return not (
            self.groups_only_in_reference or self.groups_only_in_new or self.differences
        )

    def to_text(self) -> str:
        """Return a human-readable report. An empty string means the stores match."""
        if self.matches:
            return ""
        lines: list[str] = []
        if self.groups_only_in_reference:
            groups = ", ".join(self.groups_only_in_reference)
            lines.append(f"Groups only in the reference: {groups}")
        if self.groups_only_in_new:
            lines.append(
                f"Groups only in the new store: {', '.join(self.groups_only_in_new)}"
            )
        for d in sorted(
            self.differences,
            key=lambda x: (x.group, x.variable or "", x.kind.value),
        ):
            summary = _difference_summary(d)
            lines.append(
                f"{_where(d)}: {d.kind.value}" + (f": {summary}" if summary else "")
            )
            if d.detail:
                lines.extend(f"    {line}" for line in d.detail.splitlines())
        return "\n".join(lines)


def _where(d: ComparisonDifference) -> str:
    if d.variable:
        return d.variable if not d.group else f"{d.group}/{d.variable}"
    return d.group or "<store>"


def _difference_summary(d: ComparisonDifference) -> str:
    parts: list[str] = []
    if d.n_values is not None:
        parts.append(f"{d.n_values} value(s)")
    if d.largest_diff is not None:
        parts.append(f"largest |diff| {d.largest_diff}")
    if d.tolerance is not None:
        parts.append(f"tolerance {d.tolerance}")
    return ", ".join(parts)


def compare_stores(reference: MyIcechunkStore, new: MyIcechunkStore) -> StoreComparison:
    """Compare two stores and return a report.

    Reads both stores through ``MyIcechunkStore`` only, so a VOD store's
    analyses below their calculator are compared too. The report says
    whether they match and lists every difference per group and variable.
    """
    ref_groups = reference.list_data_groups()
    new_groups = new.list_data_groups()

    result = StoreComparison(
        groups_in_reference=len(ref_groups),
        groups_in_new=len(new_groups),
        groups_only_in_reference=[g for g in ref_groups if g not in new_groups],
        groups_only_in_new=[g for g in new_groups if g not in ref_groups],
    )
    _compare_attributes(
        "", None, reference.get_root_attrs(), new.get_root_attrs(), result
    )
    for group in ref_groups:
        if group in new_groups:
            _compare_datasets(
                group, reference.read_group(group), new.read_group(group), result
            )
    return result


def without_volatile(attrs: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Return ``attrs`` without :data:`VOLATILE_ATTRIBUTES`, also nested ones."""
    kept = {}
    for key, value in attrs.items():
        path = f"{prefix}{key}"
        if path in VOLATILE_ATTRIBUTES:
            continue
        kept[key] = (
            without_volatile(value, f"{path}.") if isinstance(value, dict) else value
        )
    return kept


def _compare_attributes(
    group: str,
    name: str | None,
    ref_attrs: dict[str, Any],
    new_attrs: dict[str, Any],
    result: StoreComparison,
) -> None:
    ref_attrs = _flatten(without_volatile(ref_attrs))
    new_attrs = _flatten(without_volatile(new_attrs))
    for key in sorted(set(ref_attrs) | set(new_attrs)):
        ref_val = ref_attrs.get(key)
        new_val = new_attrs.get(key)
        if not _same(ref_val, new_val):
            label = key if name is None else f"{name}.{key}"
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.ATTRIBUTE,
                    variable=label,
                    detail=f"reference {ref_val!r} != new {new_val!r}",
                )
            )


def _flatten(attrs: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Nested attributes as dotted paths, so a report names the inner key."""
    flat: dict[str, Any] = {}
    for key, value in attrs.items():
        if isinstance(value, dict) and value:
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def _same(a: object, b: object) -> bool:
    """Attribute equality that also works for numpy arrays."""
    try:
        return bool(np.array_equal(np.asarray(a), np.asarray(b)))
    except TypeError, ValueError:
        return a == b


def _compare_datasets(
    group: str, ref_ds: xr.Dataset, new_ds: xr.Dataset, result: StoreComparison
) -> None:
    _compare_attributes(group, None, dict(ref_ds.attrs), dict(new_ds.attrs), result)

    ref_sizes, new_sizes = dict(ref_ds.sizes), dict(new_ds.sizes)
    for dim in sorted(set(ref_sizes) | set(new_sizes), key=str):
        if ref_sizes.get(dim) != new_sizes.get(dim):
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.DIMENSION,
                    variable=str(dim),
                    detail=f"size {ref_sizes.get(dim)} != {new_sizes.get(dim)}",
                )
            )

    ref_names, new_names = set(ref_ds.variables), set(new_ds.variables)
    for name in sorted(ref_names - new_names, key=str):
        kind = (
            DiffKind.COORDINATE_MISSING
            if name in ref_ds.coords
            else DiffKind.VARIABLE_MISSING
        )
        result.differences.append(
            ComparisonDifference(group=group, kind=kind, variable=str(name))
        )
    for name in sorted(new_names - ref_names, key=str):
        kind = (
            DiffKind.COORDINATE_EXTRA
            if name in new_ds.coords
            else DiffKind.VARIABLE_EXTRA
        )
        result.differences.append(
            ComparisonDifference(group=group, kind=kind, variable=str(name))
        )

    for name in sorted(ref_names & new_names, key=str):
        ref_var = ref_ds.variables[name]
        new_var = new_ds.variables[name]
        _compare_attributes(
            group, str(name), dict(ref_var.attrs), dict(new_var.attrs), result
        )
        _compare_values(group, str(name), ref_var, new_var, result)


def _compare_values(
    group: str,
    name: str,
    ref_var: xr.Variable,
    new_var: xr.Variable,
    result: StoreComparison,
) -> None:
    """Compare the values of one variable with xarray.testing.

    The attributes are compared apart (:func:`_compare_attributes`), so
    both sides go to xarray without them.
    """
    ref_var = ref_var.copy(deep=False)
    new_var = new_var.copy(deep=False)
    ref_var.attrs, new_var.attrs = {}, {}
    tolerance = FLOAT_TOLERANCES.get(name)
    try:
        if tolerance is not None and ref_var.shape == new_var.shape:
            xr.testing.assert_allclose(ref_var, new_var, rtol=0, atol=tolerance)
        else:
            xr.testing.assert_identical(ref_var, new_var)
    except AssertionError as error:
        message = "\n".join(str(error).strip().splitlines()[:_MESSAGE_LINES])
    else:
        return

    if ref_var.shape != new_var.shape:
        # Reported as a dimension difference; an identity coordinate whose
        # length changed is a coordinate change as well.
        if name in _IDENTITY_COORDINATES:
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.COORDINATE_CHANGE,
                    variable=name,
                    detail=f"length {ref_var.shape[0]} != {new_var.shape[0]}",
                )
            )
        return

    ref_vals, new_vals = ref_var.values, new_var.values
    n_values, largest = _count_differences(ref_vals, new_vals, tolerance or 0.0)
    if name in _IDENTITY_COORDINATES:
        kind = DiffKind.COORDINATE_CHANGE
    elif tolerance is None and ref_vals.dtype.kind in "fc":
        kind = DiffKind.NO_TOLERANCE
    else:
        kind = DiffKind.VALUE
    result.differences.append(
        ComparisonDifference(
            group=group,
            kind=kind,
            variable=name,
            n_values=n_values,
            largest_diff=largest,
            tolerance=tolerance,
            detail=message,
        )
    )


def _count_differences(
    ref_vals: np.ndarray, new_vals: np.ndarray, tolerance: float
) -> tuple[int, float | int | str | None]:
    """The number of differing values and the largest difference.

    A value missing in one array only counts as differing; values missing
    in both are equal, as in xarray.testing.
    """
    ref_missing = _missing_mask(ref_vals)
    new_missing = _missing_mask(new_vals)
    both = ~(ref_missing | new_missing)
    if ref_vals.dtype.kind in "fc":
        diff = np.zeros(ref_vals.shape)
        diff[both] = np.abs(ref_vals[both].astype(float) - new_vals[both].astype(float))
        differing = (ref_missing ^ new_missing) | (diff > tolerance)
        beyond = diff[both & differing]
        largest: float | int | str | None = float(beyond.max()) if beyond.size else None
        return int(differing.sum()), largest
    differing = (ref_missing ^ new_missing) | (both & (ref_vals != new_vals))
    pairs = differing & both
    if not pairs.any():
        return int(differing.sum()), None
    if ref_vals.dtype.kind in "iub":
        # Python integers, so no dtype wraps: int8 -100 vs 100 is 200.
        largest = max(
            abs(int(a) - int(b)) for a, b in zip(ref_vals[pairs], new_vals[pairs])
        )
    elif ref_vals.dtype.kind in "mM":
        largest = str(np.max(np.abs(ref_vals[pairs] - new_vals[pairs])))
    else:
        largest = str(new_vals[pairs][0])
    return int(differing.sum()), largest


def _missing_mask(values: np.ndarray) -> np.ndarray:
    """A boolean mask of the missing values of an array."""
    if values.dtype.kind in "fc":
        return np.isnan(values)
    if values.dtype.kind in "mM":
        return np.isnat(values)
    if values.dtype == object:
        return np.array(
            [
                v is None or (isinstance(v, float) and np.isnan(v))
                for v in values.ravel()
            ],
            dtype=bool,
        ).reshape(values.shape)
    return np.zeros(values.shape, dtype=bool)
