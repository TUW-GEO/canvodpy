"""
Modern Interactive Store Viewer
================================
xarray-compatible, marimo-first HTML representation for IcechunkStore.

Features:
- Pure CSS collapsible tree (branches → groups → content)
- Embedded xarray Dataset + Polars DataFrame HTML reprs
- Dark mode via xarray CSS variables
- Lazy loading of group content
- Optional marimo reactive components

Design priorities:
1. Marimo compatibility (primary)
2. Jupyter/VSCode notebooks (secondary)
3. Pure CSS (no JavaScript required)
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from html import escape
from typing import TYPE_CHECKING, Any, cast

from canvod.store_metadata import RESERVED_GROUP

if TYPE_CHECKING:
    from canvod.store.store import MyIcechunkStore

# Maps reader_format config values → human-readable labels for the viewer
_FORMAT_LABELS: dict[str, str] = {
    "sbf": "SBF",
    "rinex3": "RINEX v3.04",
    "rinex3_stripped": "RINEX v3 (signal strengths only)",
    "rinex2": "RINEX v2",
    "nmea": "NMEA",
}


@lru_cache(None)
def _load_xarray_static_files() -> tuple[str, str]:
    """Load xarray's static files (icons + CSS) for consistency."""
    try:
        from xarray.core.formatting_html import _load_static_files

        icons, css = _load_static_files()
        return icons, css
    except ImportError:
        # Fallback if xarray not available (shouldn't happen)
        return "", ""


class IcechunkStoreViewer:
    """
    Modern xarray-compatible viewer for IcechunkStore.

    Parameters
    ----------
    store : MyIcechunkStore
        The Icechunk store to visualize.
    """

    def __init__(self, store: MyIcechunkStore) -> None:
        """Initialize the viewer.

        Parameters
        ----------
        store : MyIcechunkStore
            Store to visualize.
        """
        self.store = store

    def _get_custom_css(self) -> str:
        """
        Custom CSS for Icechunk store viewer.

        Dark mode optimized, incorporates user's marimo dark mode patch.
        """
        return """
        <style>
        /* Icechunk Store Viewer - Dark mode optimized, minimal design */

        .icechunk-store-wrap {
            display: block;
            min-width: 300px;
            max-width: 900px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            font-size: 13px;
            line-height: 1.5;
            background: #1a1a1a;
            color: #e5e5e5;
            border: 1px solid #333;
            border-radius: 6px;
            overflow: hidden;
            margin: 12px 0;
        }

        /* Header - clean, no gradients */
        .icechunk-header {
            background: #222;
            color: #e5e5e5;
            padding: 14px 18px;
            border-bottom: 1px solid #333;
        }

        .icechunk-title {
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 8px;
        }

        .icechunk-path {
            font-size: 11px;
            opacity: 0.7;
            font-family: 'SF Mono', Consolas, monospace;
            word-break: break-all;
        }

        .icechunk-stats {
            display: flex;
            gap: 12px;
            margin-top: 8px;
            font-size: 11px;
            opacity: 0.8;
        }

        .stat-badge {
            padding: 2px 8px;
            border-radius: 3px;
            background: #2a2a2a;
        }

        /* Content area */
        .icechunk-content {
            max-height: 600px;
            overflow-y: auto;
        }

        /* Branch section - Level 1 hierarchy */
        .branch-section {
            position: relative;
            border-bottom: 1px solid #282828;
        }

        .branch-section:last-child {
            border-bottom: none;
        }

        /* Collapsible mechanism (pure CSS) */
        .icechunk-store-wrap input[type="checkbox"] {
            display: none;
        }

        /* Branch toggle - Level 1 (main branches) */
        .branch-toggle {
            display: block;
            padding: 12px 18px 12px 42px;
            cursor: pointer;
            user-select: none;
            transition: all 0.15s ease;
            font-weight: 600;
            font-size: 13px;
            background: linear-gradient(90deg, #2a4a2a 0%, #1f1f1f 40px);
            border-left: 3px solid #4a9a4a;
            position: relative;
        }

        .branch-toggle:hover {
            background: linear-gradient(90deg, #2f5a2f 0%, #252525 40px);
            border-left-color: #5fb05f;
        }

        /* Branch icon with tree connector */
        .branch-toggle::before {
            content: '▶';
            position: absolute;
            left: 16px;
            display: inline-block;
            transition: transform 0.15s ease;
            font-size: 9px;
            opacity: 0.7;
            color: #4a9a4a;
        }

        input:checked + .branch-toggle::before {
            transform: rotate(90deg);
        }

        /* Group section - Level 2 hierarchy */
        .group-section {
            position: relative;
            margin-left: 24px;
            border-left: 1px solid #3a3a3a;
        }

        /* Group toggle - Level 2 (nested groups) */
        .group-toggle {
            display: block;
            padding: 8px 18px 8px 36px;
            cursor: pointer;
            user-select: none;
            transition: all 0.15s ease;
            font-size: 12px;
            font-weight: 400;
            background: #1a1a1a;
            position: relative;
        }

        .group-toggle:hover {
            background: #222;
        }

        /* Tree connector line for groups */
        .group-toggle::after {
            content: '';
            position: absolute;
            left: 0;
            top: 50%;
            width: 12px;
            height: 1px;
            background: #3a3a3a;
        }

        /* Group expand/collapse indicator */
        .group-toggle::before {
            content: '▶';
            position: absolute;
            left: 16px;
            display: inline-block;
            transition: transform 0.15s ease;
            font-size: 8px;
            opacity: 0.5;
            color: #888;
        }

        input:checked + .group-toggle::before {
            transform: rotate(90deg);
        }

        /* Content visibility */
        .branch-content,
        .group-content {
            display: none;
        }

        input:checked ~ .branch-content,
        input:checked ~ .group-content {
            display: block;
        }

        /* Group content styling */
        .group-content {
            padding: 12px 18px 12px 42px;
            background: #1c1c1c;
            border-left: 1px solid #2a2a2a;
            margin-left: 12px;
        }

        .content-section {
            margin-bottom: 12px;
        }

        .content-section:last-child {
            margin-bottom: 0;
        }

        .content-section-title {
            font-size: 12px;
            font-weight: 600;
            color: #b0b0b0;
            margin-bottom: 8px;
            padding-bottom: 4px;
            border-bottom: 1px solid #2a2a2a;
        }

        /* ==========================================
           Embedded xarray - Dark mode (MINIMAL)
           ========================================== */

        /* Set xarray CSS variables only - let xarray handle everything else */
        .icechunk-store-wrap .group-content .xr-wrap {
            --xr-font-color0: rgba(255, 255, 255, 0.9);
            --xr-font-color2: rgba(255, 255, 255, 0.65);
            --xr-font-color3: rgba(255, 255, 255, 0.4);
            --xr-border-color: rgba(255, 255, 255, 0.15);
            --xr-disabled-color: rgba(255, 255, 255, 0.3);
            --xr-background-color: #1a1a1a;
            --xr-background-color-row-even: rgba(255, 255, 255, 0.03);
            --xr-background-color-row-odd: rgba(255, 255, 255, 0.06);
        }

        /* Force correct button positioning for embedded xarray */
        .icechunk-store-wrap .group-content .xr-var-attrs-in + label {
            grid-column: 6 !important;
        }

        .icechunk-store-wrap .group-content .xr-var-data-in + label {
            grid-column: 8 !important;
        }

        /* ==========================================
           Polars table dark mode
           ========================================== */

        .icechunk-store-wrap .group-content table {
            background: #1a1a1a;
            color: #e5e5e5;
            border-color: #2a2a2a;
        }

        .icechunk-store-wrap .group-content thead {
            background: #222;
        }

        .icechunk-store-wrap .group-content tbody tr:nth-child(even) {
            background: #1f1f1f;
        }

        .icechunk-store-wrap .group-content tbody tr:hover {
            background: #252525;
        }

        /* Count badges */
        .count-badge {
            font-size: 10px;
            font-weight: normal;
            opacity: 0.6;
            margin-left: 6px;
        }

        /* Dims display */
        .dims-info {
            font-size: 10px;
            font-family: 'SF Mono', Consolas, monospace;
            opacity: 0.6;
            margin-left: 10px;
        }

        /* Error messages */
        .icechunk-error {
            color: #ff6b6b;
            background: #2a1a1a;
            padding: 10px 14px;
            margin: 8px 0;
            border-left: 3px solid #ff6b6b;
            border-radius: 3px;
            font-size: 12px;
        }

        /* Empty state */
        .icechunk-empty {
            padding: 20px;
            text-align: center;
            opacity: 0.5;
            font-size: 12px;
        }

        /* Summary footer */
        .icechunk-summary {
            background: #1f1f1f;
            padding: 10px 18px;
            border-top: 1px solid #2a2a2a;
            font-size: 11px;
            opacity: 0.8;
        }

        .summary-grid {
            display: flex;
            gap: 16px;
        }

        .summary-item {
            flex: 1;
        }
        </style>
        """

    def _get_display_type(self, branch: str = "main") -> str:
        """Compute a human-readable store type label.

        Resolution order:
        1. ``source_format`` root attr (set by GNSSReader via orchestrator)
        2. Presence of ``metadata/sbf_obs`` group (legacy detection)
        3. Default: "RINEX v3.04" for gnss_store, "VOD" for vod_store
        """
        store_type = self.store.store_type
        if store_type == "vod_store":
            return "VOD"
        if store_type == "gnss_store":
            # 1. Check root-level source_format attr
            fmt = self.store.source_format
            if fmt:
                return _FORMAT_LABELS.get(fmt, fmt)
            # 2. Legacy: scan for sbf_obs group
            try:
                import zarr

                with self.store.readonly_session(branch) as session:
                    root = cast(Any, zarr.open_group(session.store, mode="r"))
                    for group_key in (
                        k for k in root.group_keys() if k != RESERVED_GROUP
                    ):
                        if f"{group_key}/metadata/sbf_obs" in root:
                            return "SBF"
            except Exception:
                pass
            return "RINEX v3.04"
        return store_type

    def _get_store_summary(self) -> dict[str, Any]:
        """Generate summary statistics for the store."""
        try:
            branches = self.store.get_branch_names()
            group_dict = self.store.get_group_names()
            total_groups = sum(len(groups) for groups in group_dict.values())
            first_branch = branches[0] if branches else "main"

            return {
                "branches": len(branches),
                "groups": total_groups,
                "path": str(self.store.store_path),
                "store_type": self.store.store_type,
                "display_type": self._get_display_type(first_branch),
            }
        except Exception as e:
            return {"error": str(e)}

    def _build_group_section(self, branch: str, group_name: str) -> str:
        """Build HTML for a single group (collapsed by default)."""
        # Delegate grids to specialized renderer
        if group_name == "grids":
            return self._build_grids_section(branch)

        # VOD stores nest as {model}/{analysis_name} — the top-level group
        # is a calculator model with no dataset of its own, only nested
        # analysis groups. Same pattern as _build_grids_section above.
        if self.store.store_type == "vod_store":
            return self._build_vod_model_section(branch, group_name)

        group_id = f"group-{uuid.uuid4()}"

        # Get dimensions info
        dims_str = ""
        try:
            # Try to get quick info without full load
            with self.store.readonly_session(branch) as session:
                import zarr

                root = cast(Any, zarr.open_group(session.store, mode="r"))
                if group_name in root:
                    group = root[group_name]
                    # Get dimensions from first array
                    arrays = list(group.array_keys())
                    if arrays:
                        first_arr = group[arrays[0]]
                        dims_str = f" • shape: {first_arr.shape}"
        except Exception:
            pass

        return f"""
        <div class="group-section">
            <input id="{group_id}" type="checkbox" />
            <label for="{group_id}" class="group-toggle">
                📁 <strong>{escape(group_name)}</strong>
                <span class="dims-info">{escape(dims_str)}</span>
            </label>
            <div class="group-content">
                {self._render_group_content(branch, group_name)}
            </div>
        </div>
        """

    def _build_vod_model_section(self, branch: str, model_name: str) -> str:
        """Build HTML for a VOD calculator model, enumerating its analyses.

        A model group (e.g. ``tau_omega_zeroth_order``) has no dataset of
        its own — only nested ``{analysis_name}`` groups, each of which
        does have a direct dataset + metadata table. Mirrors
        ``_build_grids_section``'s one-level-deeper enumeration.
        """
        model_id = f"group-{uuid.uuid4()}"

        analysis_names: list[str] = []
        try:
            with self.store.readonly_session(branch) as session:
                import zarr

                root = cast(Any, zarr.open_group(session.store, mode="r"))
                if model_name in root:
                    analysis_names = list(root[model_name].group_keys())
        except Exception:
            pass

        if not analysis_names:
            return f"""
            <div class="group-section">
                <input id="{model_id}" type="checkbox" />
                <label for="{model_id}" class="group-toggle">
                    🧮 <strong>{escape(model_name)}</strong>
                    <span class="count-badge">(empty)</span>
                </label>
                <div class="group-content">
                    <div class="icechunk-empty">No analyses stored</div>
                </div>
            </div>
            """

        analysis_label = "analysis" if len(analysis_names) == 1 else "analyses"

        analysis_sections = []
        for name in sorted(analysis_names):
            analysis_id = f"group-{uuid.uuid4()}"
            full_group = f"{model_name}/{name}"
            analysis_sections.append(f"""
            <div class="group-section">
                <input id="{analysis_id}" type="checkbox" />
                <label for="{analysis_id}" class="group-toggle">
                    📁 <strong>{escape(name)}</strong>
                </label>
                <div class="group-content">
                    {self._render_group_content(branch, full_group)}
                </div>
            </div>
            """)

        return f"""
        <div class="group-section">
            <input id="{model_id}" type="checkbox" />
            <label for="{model_id}" class="group-toggle">
                🧮 <strong>{escape(model_name)}</strong>
                <span class="count-badge">
                    ({len(analysis_names)} {analysis_label})
                </span>
            </label>
            <div class="group-content">
                {"".join(analysis_sections)}
            </div>
        </div>
        """

    def _build_grids_section(self, branch: str) -> str:
        """Build HTML for the grids group, enumerating each grid subgroup."""
        grids_id = f"group-{uuid.uuid4()}"

        # Enumerate grid subgroups
        grid_names: list[str] = []
        try:
            with self.store.readonly_session(branch) as session:
                import zarr

                root = cast(Any, zarr.open_group(session.store, mode="r"))
                if "grids" in root:
                    grids_group = root["grids"]
                    grid_names = list(grids_group.group_keys())
        except Exception:
            pass

        if not grid_names:
            return f"""
            <div class="group-section">
                <input id="{grids_id}" type="checkbox" />
                <label for="{grids_id}" class="group-toggle">
                    🌐 <strong>grids</strong>
                    <span class="count-badge">(empty)</span>
                </label>
                <div class="group-content">
                    <div class="icechunk-empty">No grids stored</div>
                </div>
            </div>
            """

        grid_label = "grid" if len(grid_names) == 1 else "grids"

        # Build nested sections for each grid
        grid_sections = []
        for name in sorted(grid_names):
            grid_sections.append(self._build_single_grid_section(branch, name))

        return f"""
        <div class="group-section">
            <input id="{grids_id}" type="checkbox" />
            <label for="{grids_id}" class="group-toggle">
                🌐 <strong>grids</strong>
                <span class="count-badge">({len(grid_names)} {grid_label})</span>
            </label>
            <div class="group-content">
                {"".join(grid_sections)}
            </div>
        </div>
        """

    def _load_grid_dataset(
        self,
        branch: str,
        name: str,
    ) -> Any:
        """Load the grid xarray Dataset from the store.

        Handles both storage layouts:
        - xarray-native: flat dataset at ``grids/{name}/``
        - polars-based: subgroups ``cells/``, ``metadata/``, etc.
        """
        import xarray as xr

        group_path = f"grids/{name}"
        with self.store.readonly_session(branch) as session:
            # Try flat xarray-native layout first (store_grid path)
            try:
                ds = xr.open_zarr(
                    session.store,
                    group=group_path,
                    consolidated=False,
                )
                if len(ds.data_vars) > 0:
                    return ds
            except Exception:
                pass

            # Fall back to polars-based layout (cells subgroup)
            ds = xr.open_zarr(
                session.store,
                group=f"{group_path}/cells",
                consolidated=False,
            )
            return ds

    def _load_grid_metadata(
        self,
        branch: str,
        name: str,
    ) -> dict[str, Any]:
        """Load grid metadata dict.

        Handles both storage layouts:
        - xarray-native: attrs on the dataset at ``grids/{name}/``
        - polars-based: JSON in ``grids/{name}/metadata`` subgroup
        """
        import json
        import math

        ds = self._load_grid_dataset(branch, name)
        attrs = dict(ds.attrs)

        # xarray-native path: attrs are directly on the dataset
        if "grid_type" in attrs and "grid_metadata" not in attrs:
            result = dict(attrs)
            # Normalize attr names: new format uses _deg suffix (already
            # in degrees); old format uses bare names (also in degrees
            # for the xarray-native path).
            if "angular_resolution_deg" not in result:
                result["angular_resolution_deg"] = result.get(
                    "angular_resolution",
                    0.0,
                )
            if "cutoff_theta_deg" not in result:
                result["cutoff_theta_deg"] = result.get(
                    "cutoff_theta",
                    0.0,
                )
            return result

        # polars-based path: JSON-serialized in metadata subgroup
        if "grid_metadata" in attrs:
            raw = json.loads(attrs["grid_metadata"])
            # cutoff_theta is in radians in the polars path
            if "cutoff_theta" in raw and "cutoff_theta_deg" not in raw:
                raw["cutoff_theta_deg"] = round(
                    math.degrees(raw["cutoff_theta"]),
                    2,
                )
            if "angular_resolution" in raw:
                raw.setdefault(
                    "angular_resolution_deg",
                    raw["angular_resolution"],
                )
            return raw

        return attrs

    def _build_single_grid_section(self, branch: str, name: str) -> str:
        """Build a collapsible section for a single grid subgroup."""
        grid_id = f"grid-{uuid.uuid4()}"

        # Read grid metadata for summary badge
        summary = ""
        try:
            meta = self._load_grid_metadata(branch, name)
            grid_type = meta.get("grid_type", "")
            # xarray-native uses "n_cells", polars-based uses "ncells"
            ncells = meta.get("n_cells", meta.get("ncells", ""))
            parts = []
            if grid_type:
                parts.append(str(grid_type))
            if ncells:
                parts.append(f"{ncells} cells")
            if parts:
                summary = " · ".join(parts)
        except Exception:
            pass

        badge = f'<span class="dims-info">{escape(summary)}</span>' if summary else ""

        return f"""
        <div class="group-section">
            <input id="{grid_id}" type="checkbox" />
            <label for="{grid_id}" class="group-toggle">
                🌐 <strong>{escape(name)}</strong>
                {badge}
            </label>
            <div class="group-content">
                {self._render_grid_content(branch, name)}
            </div>
        </div>
        """

    def _render_grid_content(self, branch: str, name: str) -> str:
        """Render a single grid's content: properties table + xarray repr."""
        content_parts: list[str] = []

        # 1. Properties table from metadata
        try:
            meta = self._load_grid_metadata(branch, name)

            display_items = [
                ("grid_type", "Grid type"),
                ("n_cells", "Cells"),
                ("ncells", "Cells"),
                ("angular_resolution_deg", "Angular resolution (deg)"),
                ("cutoff_theta_deg", "Cutoff theta (deg)"),
                ("angular_resolution_description", "Resolution meaning"),
            ]
            rows = []
            seen_labels: set[str] = set()
            for key, label in display_items:
                if key in meta and label not in seen_labels:
                    val = meta[key]
                    if val in (0, 0.0, ""):
                        continue
                    seen_labels.add(label)
                    rows.append(
                        f"<tr><td><strong>{escape(label)}</strong></td>"
                        f"<td>{escape(str(val))}</td></tr>",
                    )
            if rows:
                content_parts.append(f"""
                <div class="content-section">
                    <div class="content-section-title">
                        Grid Properties
                    </div>
                    <table style="width:auto; border-collapse:collapse;">
                        <tbody>{"".join(rows)}</tbody>
                    </table>
                </div>
                """)
        except Exception as e:
            content_parts.append(f"""
            <div class="icechunk-error">
                Failed to load grid metadata: {escape(str(e))}
            </div>
            """)

        # 2. xarray Dataset repr
        try:
            ds = self._load_grid_dataset(branch, name)
            content_parts.append(f"""
            <div class="content-section">
                <div class="content-section-title">Dataset</div>
                {ds._repr_html_()}
            </div>
            """)
        except Exception as e:
            content_parts.append(f"""
            <div class="icechunk-error">
                Failed to load grid dataset: {escape(str(e))}
            </div>
            """)

        return "".join(content_parts)

    def _render_group_content(self, branch: str, group_name: str) -> str:
        """
        Render group content: xarray Dataset + metadata table.

        This is only called when the group is expanded.
        """
        content_parts = []

        # 1. Load and display xarray Dataset
        try:
            ds = self.store.read_group(group_name, branch=branch)
            content_parts.append(f"""
            <div class="content-section">
                <div class="content-section-title">📊 Dataset</div>
                {ds._repr_html_()}
            </div>
            """)
        except Exception as e:
            content_parts.append(f"""
            <div class="icechunk-error">
                Failed to load dataset: {escape(str(e))}
            </div>
            """)

        # 2. SBF metadata dataset (if present)
        try:
            sbf_meta = self.store.read_metadata_dataset(
                group_name, "sbf_obs", branch=branch, chunks={}
            )
            content_parts.append(f"""
            <div class="content-section">
                <div class="content-section-title">📡 SBF Metadata</div>
                {sbf_meta._repr_html_()}
            </div>
            """)
        except Exception:
            pass  # No SBF metadata for this group

        # 3. Load and display metadata table
        try:
            with self.store.readonly_session(branch) as session:
                metadata_df = self.store.load_metadata(session.store, group_name)

                # Try to use marimo interactive table if available
                try:
                    import marimo as mo

                    table_widget = mo.ui.table(data=metadata_df, pagination=True)
                    table_html = table_widget._repr_html_()
                except ImportError, AttributeError:
                    # Fallback to Polars HTML for Jupyter
                    table_html = metadata_df._repr_html_()

                content_parts.append(f"""
                <div class="content-section">
                    <div class="content-section-title">
                        📋 Metadata Table
                        <span class="count-badge">
                            ({len(metadata_df)} rows)
                        </span>
                    </div>
                    {table_html}
                </div>
                """)
        except Exception as e:
            content_parts.append(f"""
            <div class="icechunk-error">
                Failed to load metadata: {escape(str(e))}
            </div>
            """)

        return "".join(content_parts)

    def _build_branch_section(self, branch: str) -> str:
        """Build HTML for a single branch with all its groups."""
        branch_id = f"branch-{uuid.uuid4()}"

        # Get groups for this branch
        try:
            group_dict = self.store.get_group_names()
            groups = group_dict.get(branch, [])
            groups_html = "".join(
                self._build_group_section(branch, group) for group in groups
            )

            is_vod = self.store.store_type == "vod_store"
            noun_singular = "model" if is_vod else "receiver"
            noun_plural = "models" if is_vod else "receivers"

            if not groups:
                groups_html = (
                    f'<div class="icechunk-empty">'
                    f"📭 No {noun_plural} in this branch</div>"
                )

            # Default to checked for "main" branch
            checked = " checked" if branch == "main" else ""

            # Separate receivers/models from grids for the count badge
            has_grids = "grids" in groups
            receiver_count = len(groups) - (1 if has_grids else 0)
            receiver_label = noun_singular if receiver_count == 1 else noun_plural

            badge_parts = []
            if receiver_count > 0:
                badge_parts.append(f"{receiver_count} {receiver_label}")
            if has_grids:
                # Count actual grid subgroups
                n_grids = 0
                try:
                    with self.store.readonly_session(branch) as session:
                        import zarr

                        root = cast(Any, zarr.open_group(session.store, mode="r"))
                        if "grids" in root:
                            n_grids = len(list(root["grids"].group_keys()))
                except Exception:
                    pass
                grid_label = "grid" if n_grids == 1 else "grids"
                badge_parts.append(f"{n_grids} {grid_label}")

            badge_text = " · ".join(badge_parts) if badge_parts else "empty"

            return f"""
            <div class="branch-section">
                <input id="{branch_id}" type="checkbox"{checked} />
                <label for="{branch_id}" class="branch-toggle">
                    🌿 <strong>{escape(branch)}</strong>
                    <span class="count-badge">
                        ({badge_text})
                    </span>
                </label>
                <div class="branch-content">
                    {groups_html}
                </div>
            </div>
            """
        except Exception as e:
            return f"""
            <div class="branch-section">
                <div class="icechunk-error">
                    Error loading branch {escape(branch)}: {escape(str(e))}
                </div>
            </div>
            """

    def _repr_html_(self) -> str:
        """Generate modern interactive HTML representation."""
        # Load xarray's static files for consistency
        icons, xr_css = _load_xarray_static_files()

        # Get store summary
        summary = self._get_store_summary()

        # Build header
        if "error" in summary:
            header = f"""
            <div class="icechunk-header">
                <div class="icechunk-title">
                    MyIcechunkStore (Error)
                </div>
                <div class="icechunk-error">
                    {escape(summary["error"])}
                </div>
            </div>
            """
            branches_html = ""
            footer = ""
        else:
            # The site name comes from the store metadata; a store without
            # it is still shown, with the command that migrates it.
            try:
                site_name = self.store.site_name
                missing_metadata = ""
            except ValueError as error:
                site_name = "site unknown"
                missing_metadata = (
                    f'<div class="icechunk-error">{escape(str(error))}</div>'
                )

            branch_label = "branch" if summary["branches"] == 1 else "branches"
            is_vod = self.store.store_type == "vod_store"
            receiver_label = (
                ("model" if is_vod else "receiver")
                if summary["groups"] == 1
                else ("models" if is_vod else "receivers")
            )

            display_type = summary.get("display_type", summary["store_type"])
            header = f"""
            <div class="icechunk-header">
                <div class="icechunk-title">
                    {escape(display_type)} MyIcechunkStore: {escape(site_name)}
                </div>
                <div class="icechunk-path">{escape(summary["path"])}</div>
                {missing_metadata}
                <div class="icechunk-stats">
                    <span class="stat-badge">
                        📊 {summary["branches"]} {branch_label}
                    </span>
                    <span class="stat-badge">
                        📡 {summary["groups"]} {receiver_label}
                    </span>
                    <span class="stat-badge">
                        💾 {escape(display_type)}
                    </span>
                </div>
            </div>
            """

            # Build branches
            try:
                branches = self.store.get_branch_names()
                if branches:
                    branches_html = "".join(
                        self._build_branch_section(branch) for branch in branches
                    )
                else:
                    branches_html = (
                        '<div class="icechunk-empty">📭 No branches in store</div>'
                    )
            except Exception as e:
                branches_html = f"""
                <div class="icechunk-error">
                    Error loading branches: {escape(str(e))}
                </div>
                """

            # Build footer
            footer = f"""
            <div class="icechunk-summary">
                <div class="summary-grid">
                    <div class="summary-item">
                        {summary["branches"]} {branch_label}
                    </div>
                    <div class="summary-item">
                        {summary["groups"]} {receiver_label}
                    </div>
                    <div class="summary-item">
                        {escape(display_type)} storage
                    </div>
                </div>
            </div>
            """

        # Assemble full HTML (DON'T load xarray CSS - let xarray handle it!)
        return f"""
        {self._get_custom_css()}
        <div class="icechunk-store-wrap">
            {header}
            <div class="icechunk-content">
                {branches_html}
            </div>
            {footer}
        </div>
        """


def add_rich_display_to_store[StoreT: type](store_class: StoreT) -> StoreT:
    """
    Add modern HTML display capabilities to IcechunkStore.

    This is a decorator that adds _repr_html_() and helper methods.

    Parameters
    ----------
    store_class : type
        The store class to enhance (typically MyIcechunkStore).

    Returns
    -------
    type
        The enhanced store class.

    Examples
    --------
    @add_rich_display_to_store
    class MyIcechunkStore:
        ...
    """

    def _repr_html_(self) -> str:
        """Rich HTML representation for notebooks."""
        viewer = IcechunkStoreViewer(self)
        return viewer._repr_html_()

    def show_tree(self) -> None:
        """Display an interactive tree view in a notebook.

        Returns
        -------
        None
        """
        try:
            from IPython.display import HTML, display

            display(HTML(self._repr_html_()))
        except ImportError:
            print(self)

    def preview(self) -> None:
        """Show a store preview (alias for show_tree).

        Returns
        -------
        None
        """
        self.show_tree()

    # Marimo-specific methods
    def to_marimo_table(
        self,
        group_name: str,
        branch: str = "main",
        pagination: bool = True,
        page_size: int = 50,
    ) -> Any:
        """
        Get metadata as interactive marimo table.

        Parameters
        ----------
        group_name : str
            Name of the group
        branch : str
            Branch name (default: "main")
        pagination : bool
            Enable pagination (default: True)
        page_size : int
            Rows per page (default: 50)

        Returns
        -------
        Any
            Interactive table widget (marimo-only).

        Raises
        ------
        ImportError
            If marimo is not available

        Examples
        --------
        In marimo notebook:

        >>> table = store.to_marimo_table("canopy_01", pagination=True)
        >>> table
        """
        try:
            import marimo as mo
        except ImportError as e:
            msg = (
                "marimo is required for interactive tables. Install with: uv add marimo"
            )
            raise ImportError(msg) from e

        with self.readonly_session(branch) as session:
            metadata_df = self.load_metadata(session.store, group_name)

        return mo.ui.table(
            data=metadata_df,
            pagination=pagination,
            page_size=page_size,
            show_column_summaries=True,
        )

    # Add methods to class
    setattr(store_class, "_repr_html_", _repr_html_)
    setattr(store_class, "show_tree", show_tree)
    setattr(store_class, "preview", preview)
    setattr(store_class, "to_marimo_table", to_marimo_table)

    return store_class


if __name__ == "__main__":
    print("🛰️ Modern IceChunk Store Viewer")
    print("📊 xarray-compatible, marimo-first design")
    print("✨ Apply @add_rich_display_to_store decorator to your store class")
