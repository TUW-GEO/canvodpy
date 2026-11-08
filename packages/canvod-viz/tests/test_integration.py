"""Integration tests for canvod-viz with actual visualization output.

These tests create real plots to verify the visualization pipeline works end-to-end.
Requires matplotlib and plotly to be installed.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

# Skip all tests if dependencies not available
pytest.importorskip("matplotlib")
go = pytest.importorskip("plotly.graph_objects")

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_output_dir():
    """Create temporary directory for test outputs."""
    temp_dir = tempfile.mkdtemp(prefix="canvod_viz_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_equal_area_grid():
    """Create mock equal-area grid with proper GridData structure."""
    import polars as pl

    # Create grid parameters
    n_theta = 8
    n_phi = 9
    ncells = n_theta * n_phi

    # Build grid data rows
    rows = []
    cell_id = 0
    for i_theta in range(n_theta):
        theta_min = (i_theta / n_theta) * (np.pi / 2)
        theta_max = ((i_theta + 1) / n_theta) * (np.pi / 2)
        theta_center = (theta_min + theta_max) / 2

        for i_phi in range(n_phi):
            phi_min = (i_phi / n_phi) * (2 * np.pi)
            phi_max = ((i_phi + 1) / n_phi) * (2 * np.pi)
            phi_center = (phi_min + phi_max) / 2

            rows.append(
                {
                    "cell_id": cell_id,
                    "phi": phi_center,
                    "theta": theta_center,
                    "phi_min": phi_min,
                    "phi_max": phi_max,
                    "theta_min": theta_min,
                    "theta_max": theta_max,
                }
            )
            cell_id += 1

    # Create Polars DataFrame
    df_grid = pl.DataFrame(rows)

    # Create mock GridData object
    class MockGridData:
        def __init__(self, ncells, grid_type, grid, metadata):
            self.ncells = ncells
            self.grid_type = grid_type
            self.grid = grid
            self.metadata = metadata

    grid = MockGridData(
        ncells=ncells,
        grid_type="equal_area",
        grid=df_grid,  # The Polars DataFrame
        metadata={"angular_resolution": 20.0, "cutoff_theta": np.pi / 2},
    )

    return grid


@pytest.fixture
def sample_vod_data(mock_equal_area_grid):
    """Generate realistic VOD data."""
    ncells = mock_equal_area_grid.ncells
    # Create gradient pattern
    data = np.linspace(0.1, 0.8, ncells)
    # Add some noise
    data += np.random.normal(0, 0.05, ncells)
    data = np.clip(data, 0, 1)
    return data


# ============================================================================
# 2D Visualization Tests
# ============================================================================


class TestVisualizer2DOutput:
    """Test 2D visualizer with actual matplotlib output."""

    def test_create_basic_2d_plot(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test creating basic 2D plot."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D

        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)

        output_file = temp_output_dir / "test_2d_basic.png"
        fig, ax = viz.plot_grid_patches(
            data=sample_vod_data, title="Test 2D Plot", save_path=output_file
        )

        # Verify file was created
        assert output_file.exists()
        assert output_file.stat().st_size > 0

        plt.close(fig)

    def test_create_2d_plot_with_custom_style(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test 2D plot with custom styling."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D, PolarPlotStyle

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)

        custom_style = PolarPlotStyle(
            cmap="plasma",
            figsize=(8, 8),
            dpi=150,
            colorbar_label="VOD",
            edgecolor="darkgray",
            linewidth=0.3,
        )

        output_file = temp_output_dir / "test_2d_custom.png"
        fig, ax = viz.plot_grid_patches(
            data=sample_vod_data, style=custom_style, save_path=output_file
        )

        assert output_file.exists()
        plt.close(fig)

    def test_create_2d_plot_without_data(self, mock_equal_area_grid, temp_output_dir):
        """Test 2D plot without data (uniform color)."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)

        output_file = temp_output_dir / "test_2d_no_data.png"
        fig, ax = viz.plot_grid_patches(
            data=None, title="Grid Structure", save_path=output_file
        )

        assert output_file.exists()
        plt.close(fig)

    def test_high_dpi_export(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test high-resolution export."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D, PolarPlotStyle

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)

        high_dpi_style = PolarPlotStyle(dpi=300)

        output_file = temp_output_dir / "test_2d_high_dpi.png"
        fig, ax = viz.plot_grid_patches(
            data=sample_vod_data, style=high_dpi_style, save_path=output_file
        )

        assert output_file.exists()
        # High DPI file should be larger
        assert output_file.stat().st_size > 50000  # At least 50KB
        plt.close(fig)


# ============================================================================
# 3D Visualization Tests
# ============================================================================


class TestVisualizer3DOutput:
    """Test 3D visualizer with actual plotly output."""

    def test_create_basic_3d_plot(self, mock_equal_area_grid, sample_vod_data):
        """Test creating basic 3D plot."""
        from canvod.viz import HemisphereVisualizer3D

        viz = HemisphereVisualizer3D(mock_equal_area_grid)

        fig = viz.plot_hemisphere_surface(data=sample_vod_data, title="Test 3D Plot")

        # Verify figure has data
        assert len(fig.data) > 0
        assert fig.layout.title.text == "Test 3D Plot"

    def test_create_3d_plot_html_export(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test 3D plot HTML export."""
        from canvod.viz import HemisphereVisualizer3D

        viz = HemisphereVisualizer3D(mock_equal_area_grid)

        fig = viz.plot_hemisphere_surface(
            data=sample_vod_data, title="Test 3D HTML Export"
        )

        output_file = temp_output_dir / "test_3d.html"
        fig.write_html(str(output_file))

        assert output_file.exists()
        assert output_file.stat().st_size > 0

        # Check HTML contains plotly
        content = output_file.read_text(encoding="utf-8")
        assert "plotly" in content.lower()

    def test_create_3d_scatter(self, mock_equal_area_grid, sample_vod_data):
        """Test 3D scatter plot."""
        from canvod.viz import HemisphereVisualizer3D

        viz = HemisphereVisualizer3D(mock_equal_area_grid)

        fig = viz.plot_hemisphere_scatter(
            data=sample_vod_data, title="3D Scatter", marker_size=8
        )

        assert len(fig.data) > 0
        assert fig.layout.title.text == "3D Scatter"

    def test_3d_plot_with_custom_colorscale(
        self, mock_equal_area_grid, sample_vod_data
    ):
        """Test 3D plot with custom colorscale."""
        from canvod.viz import HemisphereVisualizer3D

        viz = HemisphereVisualizer3D(mock_equal_area_grid)

        fig = viz.plot_hemisphere_surface(
            data=sample_vod_data, colorscale="Plasma", opacity=0.9
        )

        assert len(fig.data) > 0


# ============================================================================
# Unified Visualizer Tests
# ============================================================================


class TestUnifiedVisualizerOutput:
    """Test unified visualizer with actual output."""

    def test_publication_figure_workflow(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test complete publication figure workflow."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer(mock_equal_area_grid)

        output_file = temp_output_dir / "publication.png"
        fig, ax = viz.create_publication_figure(
            data=sample_vod_data,
            title="VOD Distribution",
            save_path=output_file,
            dpi=300,
        )

        assert output_file.exists()
        assert output_file.stat().st_size > 0
        plt.close(fig)

    def test_interactive_explorer_workflow(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test complete interactive explorer workflow."""
        from canvod.viz import HemisphereVisualizer

        viz = HemisphereVisualizer(mock_equal_area_grid)

        output_file = temp_output_dir / "explorer.html"
        fig = viz.create_interactive_explorer(
            data=sample_vod_data,
            title="VOD Explorer",
            dark_mode=True,
            save_html=output_file,
        )

        assert isinstance(fig, go.Figure)
        assert output_file.exists()
        assert output_file.stat().st_size > 0

        content = output_file.read_text(encoding="utf-8")
        assert "VOD Explorer" in content

    def test_comparison_plot_workflow(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test comparison plot workflow."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer(mock_equal_area_grid)

        output_2d = temp_output_dir / "comparison_2d.png"
        output_3d = temp_output_dir / "comparison_3d.html"

        (fig_2d, ax_2d), fig_3d = viz.create_comparison_plot(
            data=sample_vod_data, save_2d=output_2d, save_3d=output_3d
        )

        assert ax_2d.figure is fig_2d
        assert isinstance(fig_3d, go.Figure)
        assert output_2d.exists()
        assert output_3d.exists()
        plt.close(fig_2d)

    def test_style_switching(
        self, mock_equal_area_grid, sample_vod_data, temp_output_dir
    ):
        """Test switching between publication and interactive styles."""
        import matplotlib

        from canvod.viz import (
            HemisphereVisualizer,
            create_interactive_style,
            create_publication_style,
        )

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer(mock_equal_area_grid)

        # Publication style
        pub_style = create_publication_style()
        viz.set_style(pub_style)

        output_pub = temp_output_dir / "publication_style.png"
        fig_pub, ax_pub = viz.plot_2d(data=sample_vod_data, save_path=output_pub)
        assert output_pub.exists()
        plt.close(fig_pub)

        # Interactive style
        int_style = create_interactive_style(dark_mode=True)
        viz.set_style(int_style)

        output_int = temp_output_dir / "interactive_style.html"
        fig_int = viz.plot_3d(data=sample_vod_data)
        fig_int.write_html(str(output_int))
        assert output_int.exists()


# ============================================================================
# Data Edge Cases
# ============================================================================


class TestDataEdgeCases:
    """Test visualization with edge case data."""

    def test_all_nan_data(self, mock_equal_area_grid, temp_output_dir):
        """Test plotting with all NaN data."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)
        data = np.full(mock_equal_area_grid.ncells, np.nan)

        output_file = temp_output_dir / "all_nan.png"
        fig, ax = viz.plot_grid_patches(data=data, save_path=output_file)

        assert output_file.exists()
        plt.close(fig)

    def test_single_value_data(self, mock_equal_area_grid, temp_output_dir):
        """Test plotting with constant data."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)
        data = np.full(mock_equal_area_grid.ncells, 0.5)

        output_file = temp_output_dir / "constant.png"
        fig, ax = viz.plot_grid_patches(data=data, save_path=output_file)

        assert output_file.exists()
        plt.close(fig)

    def test_sparse_data(self, mock_equal_area_grid, temp_output_dir):
        """Test plotting with sparse data (mostly NaN)."""
        import matplotlib

        from canvod.viz import HemisphereVisualizer2D

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        viz = HemisphereVisualizer2D(mock_equal_area_grid)
        data = np.full(mock_equal_area_grid.ncells, np.nan)
        # Only 10% of cells have data
        valid_indices = np.random.choice(
            mock_equal_area_grid.ncells,
            size=mock_equal_area_grid.ncells // 10,
            replace=False,
        )
        data[valid_indices] = np.random.rand(len(valid_indices))

        output_file = temp_output_dir / "sparse.png"
        fig, ax = viz.plot_grid_patches(data=data, save_path=output_file)

        assert output_file.exists()
        plt.close(fig)


# ============================================================================
# Performance Integration Tests
# ============================================================================


class TestPerformanceIntegration:
    """Integration tests for performance with real plots."""

    @pytest.mark.slow
    def test_large_grid_visualization(self, temp_output_dir):
        """Test visualization with large grid (marked as slow)."""
        import matplotlib
        import polars as pl

        from canvod.viz import HemisphereVisualizer2D

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # Create large grid with proper structure
        ncells = 1000
        rows = []
        for i in range(ncells):
            phi = np.random.uniform(0, 2 * np.pi)
            theta = np.random.uniform(0, np.pi / 2)
            rows.append(
                {
                    "cell_id": i,
                    "phi": phi,
                    "theta": theta,
                    "phi_min": phi - 0.01,
                    "phi_max": phi + 0.01,
                    "theta_min": theta - 0.01,
                    "theta_max": theta + 0.01,
                }
            )

        df_grid = pl.DataFrame(rows)

        grid = Mock()
        grid.ncells = ncells
        grid.grid_type = "equal_area"
        grid.grid = df_grid
        grid.metadata = {}

        viz = HemisphereVisualizer2D(grid)
        data = np.random.rand(ncells)

        output_file = temp_output_dir / "large_grid.png"
        fig, ax = viz.plot_grid_patches(data=data, save_path=output_file)

        assert output_file.exists()
        plt.close(fig)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not slow"])
