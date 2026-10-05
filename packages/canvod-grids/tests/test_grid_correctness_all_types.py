"""Correctness regression tests parametrized across all 7 grid tessellation types.

Extends the invariants already established (via Hypothesis) for `equal_area`
in `test_grid_properties.py` to `equal_angle`, `equirectangular`, `htm`,
`geodesic`, `healpix`, and `fibonacci`. These are fixed-parameter regression
tests, not property-based sweeps -- Hypothesis coverage already exists for
`equal_area`/`htm` and is not duplicated here.

Two invariants are intentionally *not* applied uniformly across all types:

- Solid-angle-sum tolerance uses the same band already accepted for
  `equal_area` (`test_solid_angles_sum_to_hemisphere`): discrete grids
  undercount hemisphere area from edge effects, so the sum must stay in
  (0.45, 1.05) * 2*pi. Loosening this further to pass a type is not
  permitted (see docs/CLAUDE.md guardrails); a type outside this band is
  reported as failing, not re-tolerated.
- The "no below-horizon cells" check applies strictly to `theta_max` only
  for grid types whose builder explicitly clips cell bounds to the horizon
  (`equal_area`, `equal_angle`, `equirectangular`, `healpix`). For the
  triangular/Voronoi types (`htm`, `geodesic`, `fibonacci`), cells are
  filtered by *centroid* theta (the bug `c2610565` fixed) but a cell's own
  vertices/bounding box may still extend slightly past the horizon by
  documented design (see each builder's docstring) -- only the cell
  *center* is required to stay within the hemisphere for those types.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from canvod.grids import create_hemigrid
from canvod.grids._internal import phi_bbox

# Grid types whose builder clips theta_min/theta_max exactly to the horizon
# by construction -- these get the strict below-horizon bound check.
RECTANGULAR_BOUNDED_TYPES = {"equal_area", "equal_angle", "equirectangular", "healpix"}

# Per-type kwargs chosen for a reasonable resolution/runtime tradeoff.
GRID_PARAMS: dict[str, dict] = {
    "equal_area": {"angular_resolution": 10.0},
    "equal_angle": {"angular_resolution": 10.0},
    "equirectangular": {"angular_resolution": 10.0},
    "htm": {"angular_resolution": 10.0, "htm_level": 3},
    "geodesic": {"angular_resolution": 10.0, "subdivision_level": 3},
    "healpix": {"angular_resolution": 10.0, "nside": 8},
    "fibonacci": {"angular_resolution": 10.0, "n_points": 300},
}

ALL_TYPES = list(GRID_PARAMS)


@pytest.fixture(scope="module")
def built_grids() -> dict[str, object | None]:
    """Build every grid type once per test module run.

    A type whose optional dependency is missing (only `healpix`/`healpy`
    today) is stored as None rather than raising during fixture setup --
    `pytest.importorskip` raising here would abort the whole fixture and
    cascade-skip every OTHER type's tests too, not just the missing one's
    (verified: this is what happened before this fix -- 33/42 tests in
    this module silently skipped without healpy installed, not just the
    7 healpix-parametrized ones). CI does not install the `optional`
    dependency group, so this path is the one CI actually exercises.
    """
    grids: dict[str, object | None] = {}
    for grid_type in ALL_TYPES:
        try:
            grids[grid_type] = create_hemigrid(grid_type, **GRID_PARAMS[grid_type])
        except ImportError:
            grids[grid_type] = None
    return grids


def _require(built_grids: dict[str, object | None], grid_type: str):
    """Fetch a built grid, skipping only this one test if unavailable."""
    grid = built_grids[grid_type]
    if grid is None:
        pytest.skip(f"{grid_type}: optional dependency not installed")
    return grid


class TestSolidAngleSumAllTypes:
    """Invariant 1 & 2: solid angles sum to ~hemisphere area, all positive."""

    @pytest.mark.parametrize("grid_type", ALL_TYPES)
    def test_solid_angles_positive_and_sum_to_hemisphere(
        self, grid_type: str, built_grids: dict
    ) -> None:
        grid = _require(built_grids, grid_type)
        solid_angles = grid.get_solid_angles()

        assert np.all(np.isfinite(solid_angles)), (
            f"{grid_type}: solid angles contain NaN/inf"
        )
        assert np.all(solid_angles > 0), (
            f"{grid_type}: all solid angles must be positive"
        )

        total = float(np.sum(solid_angles))
        expected = 2 * np.pi

        assert total <= expected * 1.05, (
            f"{grid_type}: sum {total:.4f} exceeds hemisphere area {expected:.4f}"
        )
        assert total > expected * 0.45, (
            f"{grid_type}: sum {total:.4f} far below hemisphere area {expected:.4f}"
        )


class TestNoBelowHorizonCellsAllTypes:
    """Invariant 3: no cell's center lies below the horizon."""

    @pytest.mark.parametrize("grid_type", ALL_TYPES)
    def test_cell_center_theta_within_hemisphere(
        self, grid_type: str, built_grids: dict
    ) -> None:
        grid = _require(built_grids, grid_type)
        theta = grid.grid["theta"].to_numpy()

        assert np.all(theta >= -1e-9), f"{grid_type}: negative theta found"
        assert np.all(theta <= np.pi / 2 + 1e-9), (
            f"{grid_type}: cell center(s) below horizon, max theta = {theta.max():.6f} "
            f"(> pi/2 = {np.pi / 2:.6f})"
        )

    @pytest.mark.parametrize("grid_type", sorted(RECTANGULAR_BOUNDED_TYPES))
    def test_theta_max_clipped_to_horizon(
        self, grid_type: str, built_grids: dict
    ) -> None:
        """For rectangular-bounded types, cell bounds are clipped at build time."""
        grid = _require(built_grids, grid_type)
        theta_max = grid.grid["theta_max"].to_numpy()

        assert np.all(theta_max <= np.pi / 2 + 1e-9), (
            f"{grid_type}: theta_max exceeds horizon, "
            f"max = {theta_max.max():.6f} (> pi/2 = {np.pi / 2:.6f})"
        )


class TestNoSeamArtifactsAllTypes:
    """Invariant 4: no wraparound/duplication artifacts at phi = 0 / 2*pi.

    Rotating phi is a pure azimuthal (z-axis) rotation: it cannot change
    which cells survive the hemisphere filter (that depends only on theta,
    i.e. the z-component) or how much solid angle each cell subtends. So
    cell count and total solid angle must be exactly rotation-invariant --
    any drift indicates a seam-handling bug in `BaseGridBuilder.build()`'s
    phi-rotation logic (the code this invariant regression-tests).
    """

    @pytest.mark.parametrize("grid_type", ALL_TYPES)
    def test_ncells_and_solid_angle_stable_under_phi_rotation(
        self, grid_type: str
    ) -> None:
        if grid_type == "healpix":
            pytest.importorskip("healpy")

        base = create_hemigrid(grid_type, **GRID_PARAMS[grid_type])
        rotated = create_hemigrid(
            grid_type, **{**GRID_PARAMS[grid_type], "phi_rotation": 137.0}
        )

        assert rotated.ncells == base.ncells, (
            f"{grid_type}: cell count changed under phi_rotation "
            f"({base.ncells} -> {rotated.ncells})"
        )

        base_total = float(np.sum(base.get_solid_angles()))
        rotated_total = float(np.sum(rotated.get_solid_angles()))
        assert np.isclose(base_total, rotated_total, rtol=1e-6), (
            f"{grid_type}: total solid angle changed under phi_rotation "
            f"({base_total:.6f} -> {rotated_total:.6f})"
        )

    @pytest.mark.parametrize("grid_type", ALL_TYPES)
    def test_phi_bounds_within_expected_range(
        self, grid_type: str, built_grids: dict
    ) -> None:
        """phi_min must be in [0, 2*pi); phi_max - phi_min must be a plausible
        cell width, not a near-full-circle artifact from an unhandled seam
        crossing (excluding the legitimate full-circle zenith cap cell).
        """
        grid = _require(built_grids, grid_type)
        if "phi_min" not in grid.grid.columns:
            pytest.skip(f"{grid_type}: no phi_min/phi_max columns")

        phi_min = grid.grid["phi_min"].to_numpy()
        phi_max = grid.grid["phi_max"].to_numpy()
        theta = grid.grid["theta"].to_numpy()
        width = phi_max - phi_min

        assert np.all(phi_min >= -1e-9), f"{grid_type}: phi_min below 0"
        assert np.all(phi_min < 2 * np.pi + 1e-9), f"{grid_type}: phi_min >= 2*pi"
        assert np.all(width > 0), f"{grid_type}: non-positive phi width found"

        # The zenith cap (theta ~ 0) legitimately spans the full circle.
        non_zenith = theta > 1e-6
        if np.any(non_zenith):
            assert np.all(width[non_zenith] < 2 * np.pi * 0.9), (
                f"{grid_type}: non-zenith cell(s) with implausible near-full-circle "
                f"phi width (max width {width[non_zenith].max():.4f} rad) -- "
                "likely an unhandled seam-wraparound artifact"
            )


class TestPhiBboxHelper:
    """Direct unit tests for the shared `phi_bbox` seam-handling helper."""

    def test_no_wrap_cluster(self) -> None:
        lo, hi = phi_bbox(np.array([1.0, 1.2, 1.5]))
        assert np.isclose(lo, 1.0)
        assert np.isclose(hi, 1.5)

    def test_seam_straddling_cluster_returns_narrow_span(self) -> None:
        # Vertices at 0.01 and 6.27 rad straddle the 0/2*pi seam; the true
        # angular width is ~0.03 rad, not the naive ~6.26 rad span.
        lo, hi = phi_bbox(np.array([0.01, 6.27, 0.02]))
        width = hi - lo
        assert width < 0.1, f"seam-straddling bbox should be narrow, got width={width}"

    def test_full_circle_input_not_collapsed(self) -> None:
        # Evenly-spaced points around the whole circle: no single narrow
        # framing exists, so behavior is bounded but not asserted precise.
        phi = np.linspace(0, 2 * np.pi, 8, endpoint=False)
        lo, hi = phi_bbox(phi)
        assert hi > lo


class TestStructuralInvariantsAllTypes:
    """Invariant 5: cell IDs unique, DataFrame is Polars, ncells > 0."""

    @pytest.mark.parametrize("grid_type", ALL_TYPES)
    def test_structural_invariants(self, grid_type: str, built_grids: dict) -> None:
        grid = _require(built_grids, grid_type)

        assert isinstance(grid.grid, pl.DataFrame), f"{grid_type}: grid is not Polars"
        assert grid.ncells > 0, f"{grid_type}: ncells must be positive"
        assert len(grid.grid) == grid.ncells

        cell_ids = grid.grid["cell_id"].to_numpy()
        assert len(cell_ids) == len(np.unique(cell_ids)), (
            f"{grid_type}: duplicate cell_ids found"
        )

        assert grid.grid_type == grid_type, (
            f"{grid_type}: grid_type attribute mismatch ({grid.grid_type})"
        )


class TestRingGridCoverage:
    """Ring grids end exactly at 90° - cutoff_theta."""

    @pytest.mark.parametrize(
        "grid_type", ["equal_area", "equal_angle", "equirectangular"]
    )
    @pytest.mark.parametrize("resolution", [2.0, 5.0, 10.0, 7.0])
    def test_solid_angles_sum_to_the_hemisphere(
        self, grid_type: str, resolution: float
    ) -> None:
        grid = create_hemigrid(grid_type, angular_resolution=resolution)
        np.testing.assert_allclose(grid.get_solid_angles().sum(), 2 * np.pi)
        assert grid.grid["theta_max"].max() == pytest.approx(np.pi / 2)

    @pytest.mark.parametrize(
        "grid_type", ["equal_area", "equal_angle", "equirectangular"]
    )
    @pytest.mark.parametrize("cutoff", [10, 25])
    def test_outer_edge_is_the_cutoff(self, grid_type: str, cutoff: int) -> None:
        # The cutoff is an elevation mask: it moves the outer edge only, the
        # grid still starts at the zenith (equal_area used to drop the cells
        # within the cutoff angle of the zenith, A20 #9).
        grid = create_hemigrid(grid_type, angular_resolution=5.0, cutoff_theta=cutoff)
        assert grid.grid["theta_min"].min() == 0.0
        assert grid.grid["theta_max"].max() == pytest.approx(np.deg2rad(90 - cutoff))
        np.testing.assert_allclose(
            grid.get_solid_angles().sum(),
            2 * np.pi * (1 - np.cos(np.deg2rad(90 - cutoff))),
        )

    @pytest.mark.parametrize(
        "grid_type", ["equal_area", "equal_angle", "equirectangular"]
    )
    @pytest.mark.parametrize("resolution", [3.75, 7.0, 25.0, 30.0])
    def test_sectors_end_at_2pi_with_centres_inside(
        self, grid_type: str, resolution: float
    ) -> None:
        # 7° and 25° do not divide 360°; at 3.75° and 30° np.arange rounding
        # used to add a zero-width equirectangular sector at 2*pi.
        grid = create_hemigrid(grid_type, angular_resolution=resolution).grid
        assert grid["phi_max"].max() == pytest.approx(2 * np.pi)
        assert (grid["phi_max"] - grid["phi_min"]).min() > 1e-9
        assert (
            (grid["phi"] >= grid["phi_min"]) & (grid["phi"] <= grid["phi_max"])
        ).all()
