"""Compare two Icechunk stores within fixed, science-based tolerances.

A public comparison for the reference-store check (spec #318, seam B) and
for comparing any two stores: a production store before and after an
upgrade, two runs, a rebuilt store against the reference. It only reads,
through :class:`~canvod.store.store.MyIcechunkStore` (``list_data_groups``
and ``read_group``); it never changes how a store is written or read.

The comparison reports, per group and variable, the kind of difference,
the number of differing values and the largest absolute difference. It
also reports groups, variables and coordinates present in one store and
not the other, and a fixed list of attributes.

Tolerances are absolute and derive from the finest resolution any format
records. Every float tolerance follows from half the RINEX F14.3
resolution (0.001). See :data:`FLOAT_TOLERANCES` for the table and its
derivation, with the sources cited there (spec #318).
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np
import xarray as xr
from pydantic import BaseModel, Field, computed_field

from canvod.store.store import MyIcechunkStore

# The value of the VOD formula below (spec #318, "Tolerances"):
#   VOD = -(ln 10 / 10) * delta_snr * cos(theta).
# The factor (ln 10 / 10) turns a dB difference into a natural-log
# transmissivity difference; delta_snr carries two SNR errors.
_LN10_OVER_10 = np.log(10.0) / 10.0

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

#: The variable attributes every comparison checks. A changed value of
#: one of these is a difference; everything else (software versions,
#: timestamps, run ids, paths, hashes, the log book) is ignored.
#: Ticket #320 extends this list after looking at real stores.
COMPARED_VARIABLE_ATTRIBUTES: tuple[str, ...] = ("units", "time_system")


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
    MISSING_VALUE = "missing_value"
    ATTRIBUTE = "attribute"


class ComparisonDifference(BaseModel):
    """One difference between the two stores.

    ``group`` is the group name, or ``""`` for a store-level difference
    (a compared attribute of the store itself). ``variable`` is the
    variable, coordinate or dimension name. ``n_values`` is the number of
    differing values, ``largest_diff`` the largest absolute difference
    (a number, or ``None`` when the difference is not numeric).
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
    An empty result means the stores match.

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
            where = _x_where(d)
            if d.detail:
                lines.append(f"{where}: {d.kind.value}: {d.detail}")
            else:
                what = _difference_summary(d)
                lines.append(f"{where}: {d.kind.value}: {what}")
        return "\n".join(lines)


def _x_where(d: ComparisonDifference) -> str:
    if d.variable:
        label = d.variable if not d.group else f"{d.group}/{d.variable}"
        return label
    if d.group:
        return d.group
    return "<store>"


def _difference_summary(d: ComparisonDifference) -> str:
    parts: list[str] = []
    if d.n_values is not None:
        parts.append(f"{d.n_values} value(s)")
    if d.largest_diff is not None:
        parts.append(f"largest |diff| {d.largest_diff}")
    if d.tolerance is not None:
        parts.append(f"tolerance {d.tolerance}")
    return ", ".join(parts) if parts else "(no detail)"


def compare_stores(reference: MyIcechunkStore, new: MyIcechunkStore) -> StoreComparison:
    """Compare two stores and return a report.

    Reads both stores through ``MyIcechunkStore`` only
    (``list_data_groups`` and ``read_group``), so a VOD store's analyses
    below their calculator are compared too. The report says whether it
    matches and lists every difference per group and variable.
    """
    ref_groups = reference.list_data_groups()
    new_groups = new.list_data_groups()

    result = StoreComparison(
        groups_in_reference=len(ref_groups),
        groups_in_new=len(new_groups),
        groups_only_in_reference=[g for g in ref_groups if g not in new_groups],
        groups_only_in_new=[g for g in new_groups if g not in ref_groups],
    )

    _compare_store_attributes(reference, new, result)

    for group in ref_groups:
        if group not in new_groups:
            continue
        ref_ds = reference.read_group(group)
        new_ds = new.read_group(group)
        _compare_datasets(group, ref_ds, new_ds, result)

    return result


def _compare_store_attributes(
    reference: MyIcechunkStore, new: MyIcechunkStore, result: StoreComparison
) -> None:
    ref_sf = reference.source_format
    new_sf = new.source_format
    if ref_sf != new_sf:
        result.differences.append(
            ComparisonDifference(
                group="",
                kind=DiffKind.ATTRIBUTE,
                variable="source_format",
                detail=f"reference {ref_sf!r} != new {new_sf!r}",
            )
        )


def _compare_datasets(
    group: str, ref_ds: xr.Dataset, new_ds: xr.Dataset, result: StoreComparison
) -> None:
    _compare_dimensions(group, ref_ds, new_ds, result)
    _compare_names(group, ref_ds, new_ds, result)

    for name in sorted(set(ref_ds.variables) & set(new_ds.variables), key=str):
        _compare_variable(group, str(name), ref_ds, new_ds, result)


def _compare_dimensions(
    group: str, ref_ds: xr.Dataset, new_ds: xr.Dataset, result: StoreComparison
) -> None:
    ref_sizes = dict(ref_ds.sizes)
    new_sizes = dict(new_ds.sizes)
    for dim in sorted(set(ref_sizes) | set(new_sizes), key=str):
        r = ref_sizes.get(dim)
        n = new_sizes.get(dim)
        if r != n:
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.DIMENSION,
                    variable=str(dim),
                    detail=f"size {r} != {n}",
                )
            )


def _compare_names(
    group: str, ref_ds: xr.Dataset, new_ds: xr.Dataset, result: StoreComparison
) -> None:
    ref_names = set(ref_ds.variables)
    new_names = set(new_ds.variables)
    ref_coords = set(ref_ds.coords)
    new_coords = set(new_ds.coords)

    for name in sorted(ref_names - new_names, key=str):
        kind = (
            DiffKind.COORDINATE_MISSING
            if name in ref_coords
            else DiffKind.VARIABLE_MISSING
        )
        result.differences.append(
            ComparisonDifference(group=group, kind=kind, variable=str(name))
        )
    for name in sorted(new_names - ref_names, key=str):
        kind = (
            DiffKind.COORDINATE_EXTRA if name in new_coords else DiffKind.VARIABLE_EXTRA
        )
        result.differences.append(
            ComparisonDifference(group=group, kind=kind, variable=str(name))
        )


def _compare_variable(
    group: str,
    name: str,
    ref_ds: xr.Dataset,
    new_ds: xr.Dataset,
    result: StoreComparison,
) -> None:
    ref_var = ref_ds[name]
    new_var = new_ds[name]

    _compare_variable_attributes(group, name, ref_var, new_var, result)

    ref_vals = ref_var.values
    new_vals = new_var.values

    # A different shape is a dimension difference (already reported at the
    # dataset level) or a coordinate whose labels changed; for the identity
    # coordinates it is a coordinate change.
    if ref_vals.shape != new_vals.shape:
        if name in ("epoch", "sid"):
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.COORDINATE_CHANGE,
                    variable=name,
                    detail=f"length {ref_vals.shape[0]} != {new_vals.shape[0]}",
                )
            )
        return

    if name in ("epoch", "sid"):
        _compare_identity_coordinate(group, name, ref_vals, new_vals, result)
    else:
        _compare_values(group, name, ref_vals, new_vals, result)

    # The "File Hash", "Created", "Software" and other provenance attrs are
    # intentionally not compared; COMPARED_VARIABLE_ATTRIBUTES is the whole list.


def _compare_variable_attributes(
    group: str,
    name: str,
    ref_var: xr.DataArray,
    new_var: xr.DataArray,
    result: StoreComparison,
) -> None:
    for key in COMPARED_VARIABLE_ATTRIBUTES:
        ref_val = ref_var.attrs.get(key)
        new_val = new_var.attrs.get(key)
        if ref_val != new_val:
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.ATTRIBUTE,
                    variable=name,
                    detail=f"{key} {ref_val!r} != {new_val!r}",
                )
            )


def _compare_identity_coordinate(
    group: str,
    name: str,
    ref_vals: np.ndarray,
    new_vals: np.ndarray,
    result: StoreComparison,
) -> None:
    mismatches = ref_vals != new_vals
    if not mismatches.any():
        return
    n = int(mismatches.sum())
    # A datetime difference has a meaningful magnitude; a string difference
    # is reported by its labels.
    largest: float | int | str | None = None
    if np.issubdtype(ref_vals.dtype, np.number):
        largest = float(
            np.max(
                np.abs(
                    ref_vals[mismatches].astype(float)
                    - new_vals[mismatches].astype(float)
                )
            )
        )
    elif ref_vals.dtype.kind in "US" or ref_vals.dtype == object:
        largest = str(new_vals[mismatches][0])
    result.differences.append(
        ComparisonDifference(
            group=group,
            kind=DiffKind.COORDINATE_CHANGE,
            variable=name,
            n_values=n,
            largest_diff=largest,
            detail="labels differ (lost, extra or renamed value, or different order)",
        )
    )


def _compare_values(
    group: str,
    name: str,
    ref_vals: np.ndarray,
    new_vals: np.ndarray,
    result: StoreComparison,
) -> None:
    ref_missing = _missing_mask(ref_vals)
    new_missing = _missing_mask(new_vals)

    one_missing = ref_missing ^ new_missing
    if one_missing.any():
        result.differences.append(
            ComparisonDifference(
                group=group,
                kind=DiffKind.MISSING_VALUE,
                variable=name,
                n_values=int(one_missing.sum()),
                detail="value present in one store only (missing in the other)",
            )
        )

    both_present = ~(ref_missing | new_missing)
    if not both_present.any():
        return

    ref_p = ref_vals[both_present]
    new_p = new_vals[both_present]

    if _is_float(ref_vals):
        _compare_float_values(group, name, ref_p, new_p, result)
    else:
        _compare_exact_values(group, name, ref_p, new_p, result)


def _compare_float_values(
    group: str, name: str, ref_p: np.ndarray, new_p: np.ndarray, result: StoreComparison
) -> None:
    diff = np.abs(ref_p.astype(float) - new_p.astype(float))
    tolerance = FLOAT_TOLERANCES.get(name)
    if tolerance is not None:
        beyond = diff > tolerance
        if beyond.any():
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.VALUE,
                    variable=name,
                    n_values=int(beyond.sum()),
                    largest_diff=float(diff[beyond].max()),
                    tolerance=tolerance,
                )
            )
    else:
        differing = diff > 0
        if differing.any():
            result.differences.append(
                ComparisonDifference(
                    group=group,
                    kind=DiffKind.NO_TOLERANCE,
                    variable=name,
                    n_values=int(differing.sum()),
                    largest_diff=float(diff[differing].max()),
                    detail="no tolerance set",
                )
            )


def _compare_exact_values(
    group: str, name: str, ref_p: np.ndarray, new_p: np.ndarray, result: StoreComparison
) -> None:
    mismatches = ref_p != new_p
    if not mismatches.any():
        return
    largest: float | int | str | None
    if _is_float(ref_p):
        largest = float(
            np.max(
                np.abs(
                    ref_p[mismatches].astype(float) - new_p[mismatches].astype(float)
                )
            )
        )
    elif np.issubdtype(ref_p.dtype, np.number):
        # Compute in Python integers so no dtype wraps: int8 -100 vs 100 is
        # 200 (int8 arithmetic would wrap to 56) and uint8 0 vs 7 is 7 (not
        # 249). Booleans differ by 1.
        largest = max(
            abs(int(a) - int(b)) for a, b in zip(ref_p[mismatches], new_p[mismatches])
        )
    else:
        largest = str(new_p[mismatches][0])
    result.differences.append(
        ComparisonDifference(
            group=group,
            kind=DiffKind.VALUE,
            variable=name,
            n_values=int(mismatches.sum()),
            largest_diff=largest,
        )
    )


def _is_float(values: np.ndarray) -> bool:
    return values.dtype.kind in "fc"


def _missing_mask(values: np.ndarray) -> np.ndarray:
    """A boolean mask of the missing values of an xarray array."""
    if values.dtype.kind in "fc":
        return np.isnan(values)
    if values.dtype.kind in "mM":
        # datetime64 and timedelta64 use NaT, not NaN.
        return np.isnat(values)
    if values.dtype == object:
        return np.array(
            [
                v is None or (isinstance(v, float) and np.isnan(v))
                for v in values.ravel()
            ]
        ).reshape(values.shape)
    return np.zeros(values.shape, dtype=bool)
