"""Band registry and plotting helpers for GNSS signals."""

from typing import cast

import matplotlib.pyplot as plt
from matplotlib import gridspec, patches
from pint import Quantity
from pydantic import BaseModel

from canvod.readers.gnss_specs.constellations import (
    BEIDOU,
    GALILEO,
    GLONASS,
    GPS,
    IRNSS,
    QZSS,
    SBAS,
)


class Bands(BaseModel):
    """Registry of GNSS band definitions and properties.

    Notes
    -----
    This is a Pydantic `BaseModel` with `frozen=True` and
    `arbitrary_types_allowed=True`.

    Parameters
    ----------
    aggregate_glonass_fdma : bool, default True
        Whether to aggregate GLONASS FDMA channels into single bands.
    **kwargs
        Additional keyword arguments passed to ``BaseModel``.

    Attributes
    ----------
    BAND_PROPERTIES : dict
        Combined dictionary of all GNSS systems and their band properties.
    SYSTEM_BANDS : dict
        Mapping of GNSS system abbreviations → bands.
    OVERLAPPING_GROUPS : dict
        Mapping of overlapping groups of bands.

    """

    BAND_PROPERTIES: dict[str, dict[str, float | str | bool]]
    SYSTEM_BANDS: dict[str, dict[str, str]]
    OVERLAPPING_GROUPS: dict[str, list[str]]

    model_config = {"arbitrary_types_allowed": True, "frozen": True}

    def __init__(
        self,
        aggregate_glonass_fdma: bool = True,
        **kwargs: object,
    ) -> None:
        """Initialize bands registry."""
        # Combine all BAND_PROPERTIES from constellations
        combined_band_properties = {
            **BEIDOU.BAND_PROPERTIES,
            **GPS.BAND_PROPERTIES,
            **GALILEO.BAND_PROPERTIES,
            **GLONASS(aggregate_fdma=aggregate_glonass_fdma).BAND_PROPERTIES,
            **IRNSS.BAND_PROPERTIES,
            **SBAS.BAND_PROPERTIES,
            **QZSS.BAND_PROPERTIES,
        }

        super().__init__(
            BAND_PROPERTIES=self.strip_units(combined_band_properties),
            SYSTEM_BANDS={
                "C": BEIDOU.BANDS,
                "G": GPS.BANDS,
                "E": GALILEO.BANDS,
                "R": GLONASS(aggregate_fdma=aggregate_glonass_fdma).BANDS,
                "I": IRNSS.BANDS,
                "S": SBAS.BANDS,
                "J": QZSS.BANDS,
            },
            OVERLAPPING_GROUPS=self._make_groups(aggregate_glonass_fdma),
            **kwargs,
        )

    @staticmethod
    def strip_units(
        band_properties: dict[str, dict[str, Quantity | str | bool]],
    ) -> dict[str, dict[str, float | str | bool]]:
        """Convert a BAND_PROPERTIES dict to use only magnitudes (floats).

        Parameters
        ----------
        band_properties : dict
            Dictionary with Quantity values for frequencies.

        Returns
        -------
        dict
            Dictionary with float values (magnitudes only).

        """
        result: dict[str, dict[str, float | str | bool]] = {}
        for band, props in band_properties.items():
            clean_props: dict[str, float | str | bool] = {}
            for key, value in props.items():
                if isinstance(value, Quantity):
                    clean_props[key] = cast(float, value.magnitude)
                else:
                    clean_props[key] = value
            result[band] = clean_props
        return result

    @staticmethod
    def _make_groups(aggregate_fdma: bool) -> dict[str, list[str]]:
        """Build overlapping groups depending on FDMA aggregation."""
        if aggregate_fdma:
            return {
                "group_1": ["L1", "E1", "B1I", "B1C", "S", "J1"],
                "group_2": ["L5", "E5a", "B2a", "S", "J5", "I5"],
                "group_3": ["L2", "G2", "E5b", "B2b", "B2I", "B2", "G2a"],
                "group_4": ["E5a", "E5b", "E5"],
                "group_5": ["B2a", "B2b", "B2"],
                "group_6": ["E6", "B3I", "L6"],
                "group_7": ["G1"],
                "group_8": ["G2"],
                "group_9": ["G3"],
            }
        return {
            "group_1": ["L1", "E1", "B1I", "B1C", "S", "J1"],
            "group_2": ["L5", "E5a", "B2a", "S", "J5", "I5"],
            "group_3": ["L2", "E5b", "B2b", "B2I", "B2", "G2a"],
            "group_4": ["E5a", "E5b", "E5"],
            "group_5": ["B2a", "B2b", "B2"],
            "group_6": ["E6", "B3I", "L6"],
            "group_7": ["G1_FDMA"],
            "group_8": ["G2_FDMA"],
            "group_9": ["G3"],
        }

    def plot_bands(
        self,
        available_combinations: list[str] | None = None,
        figsize: tuple[int, int] = (16, 8),
        savepath: str | None = None,
        exclude_systems: list[str] | None = None,
    ) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
        """Draw GNSS frequency plan with frequency ordering and x-axis break.

        Parameters
        ----------
        available_combinations : list of str, optional
            List of available system-band-code combinations.
        figsize : tuple of int, default (16, 8)
            Figure size (width, height) in inches.
        savepath : str, optional
            If provided, saves the figure to this path.
        exclude_systems : list of str, optional
            List of system-band-code combinations to exclude.

        Returns
        -------
        tuple
            Tuple of (figure, (ax1, ax2)) containing the matplotlib figure and axes.

        """
        if exclude_systems is None:
            exclude_systems = []

        if available_combinations is None:
            # Default to all possible combinations if not provided
            available_combinations = []
            for system, system_bands in self.SYSTEM_BANDS.items():
                for band in system_bands:
                    for code in ["C", "L", "W", "I", "Q"]:
                        available_combinations.append(f"{system}_{band}_{code}")

        # System colors (matching the image)
        colors = {
            "C": "#D32F2F",  # Red (BeiDou)
            "E": "#00BCD4",  # Cyan (Galileo)
            "G": "#1976D2",  # Blue (GPS)
            "R": "#4CAF50",  # Green (GLONASS)
            "I": "#9C27B0",  # Purple (IRNSS)
            "S": "#FF9800",  # Orange (SBAS)
            "J": "#00BCD4",  # Light blue (QZSS)
        }

        # Get all recorded system-band combinations
        recorded_combinations = []
        for key in available_combinations:
            if any(key.startswith(ex.rsplit("_", 1)[0]) for ex in exclude_systems):
                continue  # Skip excluded combinations

            system_band = "_".join(key.split("_")[:2])  # e.g., 'G_L1', 'R_G1'
            if system_band not in recorded_combinations:
                recorded_combinations.append(system_band)

        # Sort by frequency
        band_frequencies = []
        for sys_band in recorded_combinations:
            system, band = sys_band.split("_")
            if band in self.BAND_PROPERTIES:
                freq = float(self.BAND_PROPERTIES[band]["freq"])
                band_frequencies.append((freq, sys_band))

        # Sort by frequency (lowest first)
        band_frequencies.sort()
        sorted_combinations = [combo for freq, combo in band_frequencies]

        # Define frequency break point (between L5/E5a group and L2/B3I group)
        break_freq = 1200  # MHz - adjust based on your data

        # Split into low and high frequency groups
        low_freq_combos = []
        high_freq_combos = []

        for sys_band in sorted_combinations:
            system, band = sys_band.split("_")
            freq = float(self.BAND_PROPERTIES[band]["freq"])
            if freq < break_freq:
                low_freq_combos.append(sys_band)
            else:
                high_freq_combos.append(sys_band)

        # Create figure with broken axis
        fig = plt.figure(figsize=figsize, facecolor="black")

        # Create grid: 1 row, 2 columns with different widths
        gs = gridspec.GridSpec(1, 2, width_ratios=[1, 2], wspace=0.3, figure=fig)

        ax1 = fig.add_subplot(gs[0])  # Left panel (low frequencies)
        ax2 = fig.add_subplot(gs[1])  # Right panel (high frequencies)

        for ax in [ax1, ax2]:
            ax.set_facecolor("black")

        # Plot function for each panel
        def plot_panel(
            ax: plt.Axes,
            combinations: list[str],
            panel_name: str,
        ) -> None:
            """Plot frequency bands on a panel.

            Parameters
            ----------
            ax : matplotlib.axes.Axes
                Axes to plot on.
            combinations : list of str
                System-band combinations to plot.
            panel_name : str
                Panel identifier ("left" or "right").

            Returns
            -------
            None

            """
            if not combinations:
                return

            # Rectangle dimensions
            band_height = 0.6
            y_spacing = 0.8
            current_y = 0

            freqs_in_panel = []
            bws_in_panel = []

            for sys_band in combinations:
                system, band = sys_band.split("_")
                props = self.BAND_PROPERTIES[band]
                freq = float(props["freq"])
                bw = float(props["bandwidth"])

                freqs_in_panel.append(freq)
                bws_in_panel.append(bw)

                left = freq - bw / 2
                right = freq + bw / 2

                # Create rectangle
                rect = patches.Rectangle(
                    (left, current_y),
                    bw,
                    band_height,
                    facecolor=colors.get(system, "gray"),
                    edgecolor="white",
                    linewidth=1,
                    alpha=0.9,
                )
                ax.add_patch(rect)

                # Format frequency range text
                freq_text = f"{left:.1f}-{right:.1f}"

                # Format band label
                band_label = f"{system} {band}"

                # Add text inside rectangle
                ax.text(
                    (left + right) / 2,
                    current_y + band_height / 2,
                    f"{band_label}\n{freq_text}",
                    ha="center",
                    va="center",
                    fontsize=10,
                    weight="bold",
                    color="white",
                )

                current_y += y_spacing

            # Set panel limits
            if freqs_in_panel:
                xmin = (
                    min(
                        f - bw / 2
                        for f, bw in zip(
                            freqs_in_panel,
                            bws_in_panel,
                            strict=False,
                        )
                    )
                    - 10
                )
                xmax = (
                    max(
                        f + bw / 2
                        for f, bw in zip(
                            freqs_in_panel,
                            bws_in_panel,
                            strict=False,
                        )
                    )
                    + 10
                )
                ax.set_xlim(xmin, xmax)
                ax.set_ylim(-0.5, current_y + 0.5)

            # Style axes
            ax.set_xlabel("Frequency [MHz]", fontsize=12, color="white")
            if panel_name == "left":
                ax.set_ylabel("System-Band Combinations", fontsize=12, color="white")

            ax.grid(axis="x", linestyle="-", alpha=0.3, color="white")
            ax.tick_params(colors="white", which="both")

            # Style spines
            for spine in ax.spines.values():
                spine.set_color("white")

        # Plot both panels
        plot_panel(ax1, low_freq_combos, "left")
        plot_panel(ax2, high_freq_combos, "right")

        # Add title to the figure
        fig.suptitle(
            "GNSS Frequency Bands Overview", fontsize=14, weight="bold", color="white"
        )

        # Create legend
        legend_elements = []
        all_systems = set()
        for combo in sorted_combinations:
            all_systems.add(combo.split("_")[0])

        system_names = {
            "C": "C",
            "E": "E",
            "G": "G",
            "R": "R",
            "I": "I",
            "S": "S",
            "J": "J",
        }

        legend_elements = [
            patches.Patch(color=colors[sys], label=system_names[sys])
            for sys in sorted(all_systems)
        ]

        # Place legend on the right panel
        legend = ax2.legend(
            handles=legend_elements,
            title="GNSS Systems",
            loc="upper right",
            bbox_to_anchor=(0.98, 0.98),
            fontsize=10,
            title_fontsize=11,
            frameon=True,
            facecolor="black",
            edgecolor="white",
        )

        # Style legend text
        legend.get_title().set_color("white")
        for text in legend.get_texts():
            text.set_color("white")

        # Add break indicators (optional)
        # Add text to show the frequency gap
        fig.text(
            0.5,
            0.02,
            f"Frequency break: <{break_freq} MHz | >{break_freq} MHz",
            ha="center",
            va="bottom",
            color="white",
            fontsize=10,
        )

        plt.tight_layout()
        if savepath:
            fig.savefig(savepath, dpi=300, bbox_inches="tight", facecolor="black")
        return fig, (ax1, ax2)
