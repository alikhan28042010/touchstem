"""Turn a Circuit into tactile geometry and export SVG (swell paper / embosser),
STL (3D print) and PNG (teacher preview).

All units are millimetres. Defaults follow common tactile-graphics and braille
practice; they are parameters so teachers can tune them after testing.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from .braille import translate
from .components import LEGEND_TITLE, symbol_for
from .model import Circuit


@dataclass
class Spec:
    grid: float = 36.0          # distance between grid points
    min_grid: float = 26.0
    margin: float = 14.0
    max_width: float = 200.0    # fits most 220 mm printer beds and A4 landscape
    max_height: float = 180.0
    line_w: float = 1.4         # raised line width
    line_h: float = 0.9         # raised line height (STL)
    plate_t: float = 2.0        # base plate thickness (STL)
    dot_d: float = 1.6          # braille dot base diameter
    dot_h: float = 0.7          # braille dot height (STL)
    dot_pitch: float = 2.5      # dot centre spacing inside a cell
    cell_pitch: float = 6.2     # cell to cell
    line_pitch: float = 10.0    # braille line to line
    junction_r: float = 2.0
    label_gap: float = 3.5      # clearance between labels and lines


@dataclass
class Layout:
    width: float
    height: float
    raised: object                                   # shapely (Multi)Polygon
    dots: list[tuple[float, float]] = field(default_factory=list)
    ink: list[tuple[str, float, float, float]] = field(default_factory=list)  # text, x, y, size
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- braille cells
def cell_dots(cell: str, x0: float, y0: float, spec: Spec) -> list[tuple[float, float]]:
    """Dot centres of one cell; (x0, y0) is the centre of dot 1."""
    pos = {"1": (0, 0), "2": (0, 1), "3": (0, 2), "4": (1, 0), "5": (1, 1), "6": (1, 2)}
    return [(x0 + pos[d][0] * spec.dot_pitch, y0 + pos[d][1] * spec.dot_pitch) for d in cell if d in pos]


def cells_size(n: int, spec: Spec) -> tuple[float, float]:
    return (max(n - 1, 0) * spec.cell_pitch + spec.dot_pitch, 2 * spec.dot_pitch)


def place_cells(cells: list[str], left: float, top: float, spec: Spec) -> list[tuple[float, float]]:
    dots = []
    for i, c in enumerate(cells):
        dots += cell_dots(c, left + i * spec.cell_pitch, top, spec)
    return dots


# ---------------------------------------------------------------- diagram
def build_diagram(c: Circuit, spec: Spec | None = None, lang: str = "ru") -> Layout:
    spec = spec or Spec()
    warnings: list[str] = []
    grid = spec.grid
    for extent, limit in ((c.width, spec.max_width), (c.height, spec.max_height)):
        if extent:
            grid = min(grid, (limit - 2 * spec.margin) / extent)
    if grid < spec.min_grid:
        warnings.append(f"схема крупная: шаг сетки {grid:.0f} мм меньше рекомендуемых {spec.min_grid:.0f} мм — "
                        "лучше разделить схему на части или печатать крупнее")
    grid = max(grid, spec.min_grid * 0.8)
    W = c.width * grid + 2 * spec.margin
    H = c.height * grid + 2 * spec.margin

    def P(nid: str) -> tuple[float, float]:
        n = c.nodes[nid]
        return (spec.margin + n.x * grid, spec.margin + n.y * grid)

    shapes = []
    letter_dots: list[tuple[float, float]] = []
    label_jobs = []  # (element, mid, d, n, half_width)

    def stroke(points):
        if len(points) >= 2:
            shapes.append(LineString(points).buffer(spec.line_w / 2, cap_style="round", join_style="round"))

    for e in c.elements:
        p, q = P(e.a), P(e.b)
        L = math.dist(p, q)
        d = ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
        nrm = (-d[1], d[0])
        mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        sym = symbol_for(e.type)
        if sym is None:
            stroke([p, q])
            continue
        scale = min(1.0, (L - 8) / sym.length) if sym.length > 0 else 1.0
        if scale < 1.0:
            warnings.append(f"элемент {e.id}: мало места, символ уменьшен")

        def T(u, v, s=scale):
            return (mid[0] + s * (u * d[0] + v * nrm[0]), mid[1] + s * (u * d[1] + v * nrm[1]))

        hl = sym.length * scale / 2
        stroke([p, (mid[0] - hl * d[0], mid[1] - hl * d[1])])
        stroke([(mid[0] + hl * d[0], mid[1] + hl * d[1]), q])
        for s in sym.strokes:
            stroke([T(u, v) for u, v in s])
        for f in sym.fills:
            shapes.append(Polygon([T(u, v) for u, v in f]).buffer(0))
        for letter, u, v in sym.letters:
            br = translate(letter, lang)
            cx, cy = T(u, v)
            w, h = cells_size(len(br.cells), spec)
            letter_dots += place_cells(br.cells, cx - w / 2, cy - h / 2, spec)
        if e.key:
            label_jobs.append((e, mid, d, nrm, sym.half_width * scale))

    for nid in c.nodes:
        if c.degree(nid) >= 3:
            x, y = P(nid)
            shapes.append(LineString([(x, y), (x + 0.01, y)]).buffer(spec.junction_r))

    raised = unary_union(shapes)
    obstacles = [raised.buffer(spec.label_gap)]
    for x, y in letter_dots:
        obstacles.append(box(x - 2, y - 2, x + 2, y + 2))
    frame = box(spec.margin * 0.35, spec.margin * 0.35, W - spec.margin * 0.35, H - spec.margin * 0.35)

    dots = list(letter_dots)
    ink = []
    for e, mid, d, nrm, hw in label_jobs:
        br = translate(str(e.key), lang)
        w, h = cells_size(len(br.cells), spec)
        best, best_cost = None, None
        candidates = []
        for side in (1, -1):
            off = hw + spec.label_gap + (abs(nrm[0]) * w + abs(nrm[1]) * h) / 2 + 1
            candidates.append((mid[0] + side * off * nrm[0], mid[1] + side * off * nrm[1]))
        for along in (0.25, -0.25):
            for side in (1, -1):
                off = hw + spec.label_gap + (abs(nrm[0]) * w + abs(nrm[1]) * h) / 2 + 1
                shift = along * grid
                candidates.append((mid[0] + side * off * nrm[0] + shift * d[0],
                                   mid[1] + side * off * nrm[1] + shift * d[1]))
        for cx, cy in candidates:
            rect = box(cx - w / 2 - 1, cy - h / 2 - 1, cx + w / 2 + 1, cy + h / 2 + 1)
            cost = sum(rect.intersection(o).area for o in obstacles) + rect.difference(frame).area * 10
            if best_cost is None or cost < best_cost:
                best, best_cost = (cx, cy, rect), cost
            if cost == 0:
                break
        cx, cy, rect = best
        if best_cost and best_cost > 0.5:
            warnings.append(f"подпись {e.key} касается линий — проверьте превью")
        dots += place_cells(br.cells, cx - w / 2, cy - h / 2, spec)
        obstacles.append(rect.buffer(spec.label_gap / 2))
        ink.append((str(e.key), cx, cy - h / 2 - 2.5, 3.2))

    return Layout(W, H, raised, dots, ink, warnings)


# ---------------------------------------------------------------- legend
def build_legend(c: Circuit, lang: str = "ru", spec: Spec | None = None) -> tuple[Layout, str]:
    spec = spec or Spec()
    max_cells = int((spec.max_width - 2 * spec.margin) // spec.cell_pitch)
    lines: list[tuple[list[str], str]] = []
    warnings: list[str] = []

    def add(text: str):
        br = translate(text, lang)
        warnings.extend(br.warnings)
        cells = br.cells
        # wrap on blank cells
        while len(cells) > max_cells:
            cut = max((i for i, cc in enumerate(cells[:max_cells + 1]) if cc == "0"), default=max_cells)
            lines.append((cells[:cut], ""))
            cells = cells[cut + 1:] if cut < len(cells) and cells[cut] == "0" else cells[cut:]
        lines.append((cells, text))

    add(LEGEND_TITLE[lang])
    for key, text in c.legend(lang):
        add(f"{key} {text}")
    longest = max((len(cl) for cl, _ in lines), default=1)
    W = max(cells_size(longest, spec)[0] + 2 * spec.margin, 80)
    H = len(lines) * spec.line_pitch + 2 * spec.margin
    dots, ink = [], []
    for i, (cells, text) in enumerate(lines):
        top = spec.margin + i * spec.line_pitch
        dots += place_cells(cells, spec.margin, top, spec)
        if text:
            ink.append((text, spec.margin, top - 1.8, 3.0))
    unicode_text = "\n".join("".join(chr(0x2800 | sum(1 << (int(d) - 1) for d in cc if d in "123456")) for cc in cl)
                             for cl, _ in lines)
    return Layout(W, H, Polygon(), dots, ink, sorted(set(warnings))), unicode_text


# ---------------------------------------------------------------- export: SVG
def _poly_paths(geom) -> list[str]:
    polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    paths = []
    for p in polys:
        if p.is_empty:
            continue
        rings = [p.exterior, *p.interiors]
        d = " ".join("M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in r.coords) + " Z" for r in rings)
        paths.append(d)
    return paths


def to_svg(layout: Layout, spec: Spec | None = None, ink: bool = False) -> str:
    """ink=False: pure black tactile master for swell paper. ink=True: adds gray print labels for teachers."""
    spec = spec or Spec()
    w, h = layout.width, layout.height
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.1f}mm" height="{h:.1f}mm" '
           f'viewBox="0 0 {w:.2f} {h:.2f}">',
           f'<rect width="{w:.2f}" height="{h:.2f}" fill="white"/>']
    for d in _poly_paths(layout.raised):
        out.append(f'<path d="{d}" fill="black" fill-rule="evenodd"/>')
    r = spec.dot_d / 2
    for x, y in layout.dots:
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="black"/>')
    if ink:
        for text, x, y, size in layout.ink:
            safe = text.replace("&", "&amp;").replace("<", "&lt;")
            out.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" font-family="Arial" fill="#1a73e8">{safe}</text>')
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- export: STL
def to_stl(layout: Layout, spec: Spec | None = None) -> bytes:
    from manifold3d import CrossSection, Manifold
    import numpy as np
    import trimesh

    spec = spec or Spec()
    W, H = layout.width, layout.height
    parts = [Manifold.cube([W, H, spec.plate_t])]
    polys = [layout.raised] if layout.raised.geom_type == "Polygon" else list(getattr(layout.raised, "geoms", []))
    for p in polys:
        if p.is_empty:
            continue
        rings = [[(x, H - y) for x, y in p.exterior.coords[:-1]]]
        rings += [[(x, H - y) for x, y in r.coords[:-1]] for r in p.interiors]
        cs = CrossSection(rings)
        parts.append(cs.extrude(spec.line_h).translate([0, 0, spec.plate_t - 0.05]))
    r = spec.dot_d / 2
    dome = Manifold.sphere(r, 20).scale([1, 1, spec.dot_h / r])
    for x, y in layout.dots:
        parts.append(dome.translate([x, H - y, spec.plate_t]))
    solid = Manifold.batch_boolean(parts, __import__("manifold3d").OpType.Add)
    mesh = solid.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
    buf = io.BytesIO()
    tm.export(buf, file_type="stl")
    return buf.getvalue()


# ---------------------------------------------------------------- export: PNG preview
def to_png(layout: Layout, spec: Spec | None = None, dpi: int = 110) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, PathPatch
    from matplotlib.path import Path as MPath

    spec = spec or Spec()
    fig, ax = plt.subplots(figsize=(layout.width / 25.4, layout.height / 25.4), dpi=dpi)
    ax.set_xlim(0, layout.width)
    ax.set_ylim(layout.height, 0)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), layout.width, layout.height, fill=False, ec="#999", lw=0.8))
    polys = [layout.raised] if layout.raised.geom_type == "Polygon" else list(getattr(layout.raised, "geoms", []))
    for p in polys:
        if p.is_empty:
            continue
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            pts = list(ring.coords)
            verts += pts
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 2) + [MPath.CLOSEPOLY]
        ax.add_patch(PathPatch(MPath(verts, codes), fc="black", ec="none"))
    for x, y in layout.dots:
        ax.add_patch(Circle((x, y), spec.dot_d / 2, fc="black"))
    for text, x, y, size in layout.ink:
        ax.text(x, y, text, fontsize=size * 2.2, color="#1a73e8", ha="left" if len(text) > 3 else "center", va="bottom")
    fig.subplots_adjust(0, 0, 1, 1)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
