"""Tests for styles module — RSE style and Colorscale."""

import pytest

from canvod.viz.styles import (
    RSE_COLORS,
    Colorscale,
    PlotStyle,
    _rse_rcparams,
    apply_rse_style,
    create_rse_style,
    fix_figure_for_dark_mode,
    rse_context,
    rse_style,
    style_colorbar,
)


class TestRSEStyle:
    def test_rse_colors_length(self):
        assert len(RSE_COLORS) == 8

    def test_rse_rcparams_keys(self):
        params = _rse_rcparams()
        assert "figure.dpi" in params
        assert params["figure.dpi"] == 300
        assert params["axes.titlesize"] == 14

    def test_create_rse_style(self):
        style = create_rse_style()
        assert isinstance(style, PlotStyle)
        assert style.dark_mode is False
        assert style.font_size == 11

    def test_apply_rse_style(self):
        import matplotlib.pyplot as plt

        original_dpi = plt.rcParams["figure.dpi"]
        params = apply_rse_style()
        assert plt.rcParams["figure.dpi"] == 300
        assert params["figure.dpi"] == 300
        # Restore
        plt.rcParams["figure.dpi"] = original_dpi

    def test_rse_context(self):
        import matplotlib.pyplot as plt

        original_dpi = plt.rcParams["figure.dpi"]
        with rse_context():
            assert plt.rcParams["figure.dpi"] == 300
        assert plt.rcParams["figure.dpi"] == original_dpi

    def test_rse_style_decorator(self):
        @rse_style
        def make_plot():
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots()
            ax.plot([1, 2], [1, 2])
            return fig, [ax]

        fig, axes = make_plot()
        assert fig is not None
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_fix_figure_for_dark_mode(self):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        fix_figure_for_dark_mode(fig)
        assert fig.patch.get_facecolor() == (1.0, 1.0, 1.0, 1.0)
        plt.close(fig)

    def test_style_colorbar(self):
        import matplotlib.pyplot as plt
        import numpy as np

        fig, ax = plt.subplots()
        im = ax.imshow(np.random.rand(5, 5))
        cbar = fig.colorbar(im)
        result = style_colorbar(cbar, label="Test")
        assert result is cbar
        plt.close(fig)


class TestColorscale:
    def test_from_matplotlib(self):
        cs = Colorscale.from_matplotlib("viridis", n_colors=10)
        assert cs.name == "viridis"
        assert len(cs.stops) == 10
        assert cs.stops[0][0] == 0.0
        assert cs.stops[-1][0] == pytest.approx(1.0)

    def test_from_colors(self):
        cs = Colorscale.from_colors(["red", "green", "blue"], name="rgb")
        assert cs.name == "rgb"
        assert len(cs.stops) == 3

    def test_to_plotly(self):
        cs = Colorscale.from_colors(["red", "blue"])
        plotly_cs = cs.to_plotly()
        assert len(plotly_cs) == 2
        assert plotly_cs[0] == (0.0, "red")

    def test_to_matplotlib(self):
        cs = Colorscale.from_matplotlib("plasma", n_colors=10)
        cmap = cs.to_matplotlib(n_colors=64)
        assert cmap.name == "plasma"
        assert cmap.N == 64

    def test_roundtrip_hex_colors(self):
        cs = Colorscale.from_colors(["#ff0000", "#00ff00", "#0000ff"])
        cmap = cs.to_matplotlib(n_colors=10)
        assert cmap is not None
