"""Interactive hemisphere selectors for marimo and Jupyter notebooks.

Needs the optional extra: ``pip install "canvod-viz[widgets]"``.
"""

try:
    import anywidget
except ImportError as exc:
    msg = (
        "canvod.viz.widgets needs anywidget. Install it with: "
        'pip install "canvod-viz[widgets]"'
    )
    raise ImportError(msg) from exc

from canvod.viz.widgets.hemisphere_widgets import (
    HemisphereSelector2D,
    HemisphereSelector3D,
)

__all__ = ["HemisphereSelector2D", "HemisphereSelector3D"]
