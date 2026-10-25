# /// script
# requires-python = ">=3.12"
# dependencies = ["resvg-py==0.5.0", "pillow>=10"]
# ///
"""Draw the canVODpy logo for the terminal: ``canvodpy/cli/logo_frames.txt.gz``.

The CLI shows the logo at the start of a run, for ``--version`` and for
``canvodpy`` without a command (``canvodpy.cli.banner``): the tree and
the lettering, and the satellite flying in from the left. This script
draws the frames of that flight from the SVG; the last frame is the logo.

Each frame is drawn in quadrant block characters: a character cell holds
2 x 2 pixels, and a cell is about twice as tall as wide, so the SVG is
scaled to twice its width in height to keep the logo's proportions.

The satellite (one path of the SVG, ``--satellite``) starts left of the
canvas, turned flat and smaller, high above the crown, and eases into its
place, turning to its own tilt and growing to its size. At its own tilt
it would cut through the crown on the way, hence the flat start. The
script stops if the satellite touches the crown (``--crown``) in any frame
before the last.

Run it again when the logo changes:

    uv run scripts/render_logo.py docs/assets/logo/canvodpy_logo_dark_mode.svg \\
        canvodpy/src/canvodpy/cli/logo_frames.txt.gz

Only the shapes are used (the alpha channel), so either colour version of
the SVG gives the same frames; the CLI colours them for the terminal.
"""

import argparse
import gzip
import io
import re
from pathlib import Path

import resvg_py  # ty: ignore[unresolved-import]  # only in this script's environment
from PIL import Image, ImageChops

#: Quadrant blocks by their pixels: top left + 2 top right + 4 bottom left + 8 bottom right.
QUADRANTS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"

#: Supersampling of the rendering before it is reduced to cells.
SUPERSAMPLE = 8

#: Alpha (0-255) above which a pixel is set.
THRESHOLD = 110


class Canvas:
    """Renders SVG markup of the logo's viewBox onto the terminal grid."""

    def __init__(self, svg: str, columns: int) -> None:
        self.head = svg[: svg.index(">", svg.index("<svg")) + 1]
        view_box = re.search(r'viewBox="([^"]+)"', self.head)
        if view_box is None:
            raise SystemExit("the SVG has no viewBox")
        _, _, self.vb_w, self.vb_h = map(float, view_box.group(1).split())
        self.columns = columns
        self.px_h = round(columns * self.vb_h / self.vb_w)
        self.px_h += self.px_h % 2  # pixel rows, two per character row
        self.w = 2 * columns * SUPERSAMPLE
        self.h = self.px_h * SUPERSAMPLE

    def render(self, body: str) -> Image.Image:
        """Alpha of ``body`` (SVG elements in viewBox units), supersampled."""
        sx, sy = self.w / self.vb_w, self.h / self.vb_h
        doc = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}"><g transform="scale({sx} {sy})">{body}</g></svg>'
        )
        png = bytes(resvg_py.svg_to_bytes(svg_string=doc))
        return Image.open(io.BytesIO(png)).getchannel("A")

    def centre(self, alpha: Image.Image) -> tuple[float, float]:
        """Centre of the set pixels of ``alpha``, in viewBox units."""
        bbox = alpha.getbbox()
        if bbox is None:
            raise SystemExit("the drawn shape is empty")
        x0, y0, x1, y1 = bbox
        return (x0 + x1) / 2 * self.vb_w / self.w, (y0 + y1) / 2 * self.vb_h / self.h

    def text(self, alpha: Image.Image) -> str:
        """``alpha`` as quadrant blocks, one line per character row."""
        width = 2 * self.columns
        small = alpha.resize((width, self.px_h), Image.Resampling.BOX)
        pixels = small.tobytes()  # one byte per pixel (alpha), row by row
        on = [
            [pixels[y * width + x] > THRESHOLD for x in range(width)]
            for y in range(self.px_h)
        ]
        return "\n".join(
            "".join(
                QUADRANTS[
                    on[y][x]
                    + 2 * on[y][x + 1]
                    + 4 * on[y + 1][x]
                    + 8 * on[y + 1][x + 1]
                ]
                for x in range(0, 2 * self.columns, 2)
            ).rstrip()
            for y in range(0, self.px_h, 2)
        )


def flight(satellite: str, centre: tuple[float, float], t: float) -> str:
    """The satellite at time ``t``: 0 left of the canvas, 1 in its place."""
    cx, cy = centre
    eased = 1 - (1 - t) ** 3  # fast at first, slowing down into its place
    angle = -28 * (1 - eased)  # flat at the start, its own tilt at the end
    scale = 0.55 + 0.45 * eased
    x = -120 + (cx + 120) * eased
    y = 22 + (cy - 22) * eased  # high above the crown, down to its place
    return (
        f'<g transform="translate({x} {y}) rotate({angle}) scale({scale}) '
        f'translate({-cx} {-cy})">{satellite}</g>'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("svg", type=Path)
    parser.add_argument(
        "out", type=Path, help="frames, gzipped, separated by form feeds"
    )
    parser.add_argument("--columns", type=int, default=80)
    parser.add_argument("--frames", type=int, default=24, help="frames after the first")
    parser.add_argument(
        "--satellite", type=int, default=1, help="index of the satellite's path"
    )
    parser.add_argument(
        "--crown", type=int, default=0, help="index of the crown's path"
    )
    args = parser.parse_args()

    svg = args.svg.read_text(encoding="utf-8")
    paths = re.findall(r"<path[^>]*/>", svg, re.S)
    canvas = Canvas(svg, args.columns)
    satellite = paths[args.satellite]
    ground = canvas.render(
        "".join(p for i, p in enumerate(paths) if i != args.satellite)
    )
    crown = canvas.render(paths[args.crown])
    centre = canvas.centre(canvas.render(satellite))

    frames = []
    for k in range(args.frames + 1):
        t = k / args.frames
        sat = canvas.render(flight(satellite, centre, t))
        if t < 1 and (touch := ImageChops.multiply(sat, crown).getbbox()):
            raise SystemExit(f"frame {k}: the satellite touches the crown at {touch}")
        frames.append(canvas.text(ImageChops.lighter(ground, sat)))
    rows = {frame.count("\n") for frame in frames}
    if len(rows) != 1:
        raise SystemExit(f"frames of different heights: {rows}")
    args.out.write_bytes(gzip.compress(("\f".join(frames) + "\n").encode(), mtime=0))
    print(f"{len(frames)} frames of {rows.pop() + 1} rows -> {args.out}")


if __name__ == "__main__":
    main()
