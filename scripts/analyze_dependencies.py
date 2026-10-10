"""Print the dependencies between the packages of this repository.

The dependencies come from the ``[project] dependencies`` of each
``pyproject.toml`` (``packages/*`` and ``canvodpy``); optional dependencies
and dependency groups are left out. Each package belongs to one layer, and a
package may depend only on packages of its own layer or of a lower one: the
script exits non-zero if a package is missing from ``LAYERS`` or depends on
a higher layer.

Usage: ``python scripts/analyze_dependencies.py --format report|mermaid``

- ``report``: the dependencies, the coupling of each package, and the
  packages each one needs, as Markdown.
- ``mermaid``: the dependency graph, grouped by layer, as a Mermaid block;
  without canvodpy and without dependencies implied by others (see
  ``drawn_edges``).
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Layers from the lowest to the highest, with their packages.
LAYERS: list[tuple[str, list[str]]] = [
    ("Foundation", ["canvod-utils", "canvod-config"]),
    ("Data input", ["canvod-readers", "canvod-auxiliary", "canvod-preflight"]),
    ("Computation", ["canvod-vod", "canvod-grids", "canvod-ops"]),
    ("Persistence", ["canvod-store-metadata", "canvod-store"]),
    ("Presentation", ["canvod-viz"]),
    ("Orchestration", ["canvodpy"]),
]


def _requirement_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]


def read_dependencies() -> dict[str, list[str]]:
    """Return each package with the packages of this repository it depends on."""
    projects = {}
    for path in [
        *sorted(ROOT.glob("packages/*/pyproject.toml")),
        ROOT / "canvodpy/pyproject.toml",
    ]:
        project = tomllib.loads(path.read_text())["project"]
        projects[project["name"]] = [
            _requirement_name(r) for r in project.get("dependencies", [])
        ]
    return {
        name: sorted(d for d in deps if d in projects)
        for name, deps in projects.items()
    }


def check_layers(deps: dict[str, list[str]]) -> list[str]:
    """Return the problems: packages without a layer, dependencies on a higher layer."""
    level = {pkg: i for i, (_, pkgs) in enumerate(LAYERS) for pkg in pkgs}
    problems = [f"{pkg} has no layer in LAYERS" for pkg in deps if pkg not in level]
    problems += [
        f"{pkg} is in LAYERS but has no pyproject.toml"
        for pkg in level
        if pkg not in deps
    ]
    for pkg, targets in deps.items():
        for target in targets:
            if pkg in level and target in level and level[target] > level[pkg]:
                problems.append(
                    f"{pkg} ({LAYERS[level[pkg]][0]}) depends on {target} ({LAYERS[level[target]][0]})"
                )
    return problems


#: Left out of the graph: it depends on every other package.
UMBRELLA = "canvodpy"


def drawn_edges(deps: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return the dependencies to draw: without the umbrella package, and
    without a dependency that a path through another package already implies
    (e.g. canvod-store -> canvod-utils, implied by canvod-store ->
    canvod-store-metadata -> canvod-config -> canvod-utils)."""
    drawn = {}
    for pkg, targets in deps.items():
        if pkg == UMBRELLA:
            continue
        through_others = {n for t in targets for n in _needs(t, deps)}
        drawn[pkg] = [t for t in targets if t not in through_others]
    return drawn


def mermaid(deps: dict[str, list[str]]) -> str:
    """Return the dependency graph as a Mermaid block, one subgraph per layer
    (see :func:`drawn_edges` for the dependencies it leaves out)."""
    edges = drawn_edges(deps)
    node = {pkg: pkg.removeprefix("canvod-").replace("-", "_").upper() for pkg in edges}
    lines = ["```mermaid", "graph TD"]
    for title, pkgs in reversed(LAYERS):
        pkgs = [p for p in pkgs if p in edges]
        if not pkgs:
            continue
        lines.append(f'    subgraph {title.replace(" ", "_").upper()}["{title}"]')
        lines += [f'        {node[p]}["{p}"]' for p in pkgs]
        lines.append("    end")
    lines.append("")
    for _, pkgs in reversed(LAYERS):
        for pkg in pkgs:
            if edges.get(pkg):
                targets = " & ".join(node[t] for t in edges[pkg])
                lines.append(f"    {node[pkg]} --> {targets}")
    lines.append("```")
    return "\n".join(lines)


def _needs(pkg: str, deps: dict[str, list[str]]) -> list[str]:
    """Return every package ``pkg`` needs, directly or through others."""
    seen: set[str] = set()
    todo = list(deps[pkg])
    while todo:
        target = todo.pop()
        if target not in seen:
            seen.add(target)
            todo += deps[target]
    return sorted(seen)


def report(deps: dict[str, list[str]]) -> str:
    """Return the coupling table and the packages each package needs, as Markdown."""
    dependents = {pkg: sorted(p for p, ts in deps.items() if pkg in ts) for pkg in deps}
    order = [pkg for _, pkgs in LAYERS for pkg in pkgs]
    lines = [
        f"{len(deps)} packages, {sum(len(t) for t in deps.values())} dependencies between them.",
        "",
        "| Layer | Package | Depends on (Ce) | Depended on by (Ca) | Instability |",
        "|---|---|:-:|:-:|:-:|",
    ]
    layer_of = {pkg: title for title, pkgs in LAYERS for pkg in pkgs}
    for pkg in order:
        ce, ca = len(deps[pkg]), len(dependents[pkg])
        instability = f"{ce / (ce + ca):.2f}" if ce + ca else "-"
        lines.append(f"| {layer_of[pkg]} | `{pkg}` | {ce} | {ca} | {instability} |")
    lines += [
        "",
        "| Package | Needs, directly or through other packages |",
        "|---|---|",
    ]
    for pkg in order:
        needs = ", ".join(f"`{p}`" for p in _needs(pkg, deps)) or "nothing"
        lines.append(f"| `{pkg}` | {needs} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--format", choices=["report", "mermaid"], default="report")
    args = parser.parse_args()
    deps = read_dependencies()
    problems = check_layers(deps)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(report(deps) if args.format == "report" else mermaid(deps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
