"""Analysis subpackage for canvod-grids.

Per-cell and global analysis of VOD hemisphere-grid datasets: filtering,
masking, weighting, temporal/spatial aggregation, and persistent storage
of precomputed results.

Modules
-------
filtering           Global statistical filters (IQR, Z-score).
per_cell_filtering  Per-cell statistical filters.
masking             Spatial and temporal mask construction.
solar               Solar geometry computations.
weighting           Per-cell weight calculators.
temporal            Weighted temporal aggregation and diurnal analysis.
spatial             Per-cell spatial statistics.
per_cell_analysis   Multi-dataset per-cell VOD analysis.

The storage of analysis results moved to ``canvod.store.AnalysisStorage``.
"""

# Left over from development; moved to canvod.store.AnalysisStorage.
from canvod.grids.analysis.analysis_storage import AnalysisStorage
from canvod.grids.analysis.filtering import (
    Filter,
    FilterPipeline,
    IQRFilter,
    SIDPatternFilter,
    ZScoreFilter,
)
from canvod.grids.analysis.masking import (
    SpatialMask,
    create_elevation_mask,
    create_hemisphere_mask,
)
from canvod.grids.analysis.per_cell_analysis import (
    PerCellVODAnalyzer,
    extract_percell_coverage,
    extract_percell_stats,
    extract_percell_temporal_stats,
    percell_to_grid_counts,
    percell_to_grid_data,
)
from canvod.grids.analysis.per_cell_filtering import (
    PerCellFilter,
    PerCellFilterPipeline,
    PerCellIQRFilter,
    PerCellZScoreFilter,
)
from canvod.grids.analysis.solar import SolarPositionCalculator
from canvod.grids.analysis.spatial import VODSpatialAnalyzer
from canvod.grids.analysis.temporal import TemporalAnalysis
from canvod.grids.analysis.weighting import WeightCalculator

__all__ = [
    # Filters
    "Filter",
    "FilterPipeline",
    "IQRFilter",
    "PerCellFilter",
    "PerCellFilterPipeline",
    "PerCellIQRFilter",
    "PerCellVODAnalyzer",
    "PerCellZScoreFilter",
    "SIDPatternFilter",
    # Solar
    "SolarPositionCalculator",
    # Masking
    "SpatialMask",
    # Analysis
    "TemporalAnalysis",
    "VODSpatialAnalyzer",
    # Weighting
    "WeightCalculator",
    "ZScoreFilter",
    "create_elevation_mask",
    "create_hemisphere_mask",
    "extract_percell_coverage",
    "extract_percell_stats",
    "extract_percell_temporal_stats",
    "percell_to_grid_counts",
    "percell_to_grid_data",
]
