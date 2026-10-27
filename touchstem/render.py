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
    plate_t: float = 1.6        # base plate thickness (STL)
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
    texture: object = field(default_factory=Polygon)   # low relief (grid points etc.), excluded from spacing rules
    hotspots: list[dict] = field(default_factory=list)  # touchable regions for the living sheet (mm, plate coords)
    corner: float = 8.0                                  # orientation cut, top-left corner (mm)


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
    hotspots: list[dict] = []
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
            hotspots.append({"id": e.id, "key": e.key, "type": e.type, "x": round(mid[0], 1), "y": round(mid[1], 1),
                             "r": round(max(hl, sym.half_width * scale) + 5, 1)})

    for nid in c.nodes:
        if c.degree(nid) >= 3:
            x, y = P(nid)
            shapes.append(LineString([(x, y), (x + 0.01, y)]).buffer(spec.junction_r))
            hotspots.append({"id": "node:" + nid, "key": None, "type": "junction", "x": round(x, 1), "y": round(y, 1),
                             "r": 5.0})

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
        for along in (0.25, -0.25, 0.4, -0.4):
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
        if rect.distance(raised) < 1.5:
            warnings.append(f"подпись {e.key} слишком близко к линии — проверьте превью")
        dots += place_cells(br.cells, cx - w / 2, cy - h / 2, spec)
        obstacles.append(rect.buffer(spec.label_gap / 2))
        ink.append((str(e.key), cx, cy - h / 2 - 2.5, 3.2))
        for hs in hotspots:   # the braille number also answers when touched
            if hs["id"] == e.id:
                hs["lx"], hs["ly"] = round(cx, 1), round(cy, 1)

    return Layout(W, H, raised, dots, ink, warnings, hotspots=hotspots)


# ---------------------------------------------------------------- legend
def build_legend(c: Circuit, lang: str = "ru", spec: Spec | None = None) -> tuple[Layout, str]:
    return build_text_legend([LEGEND_TITLE[lang]] + [f"{key} {text}" for key, text in c.legend(lang)], lang, spec)


def build_text_legend(texts: list[str], lang: str = "ru", spec: Spec | None = None) -> tuple[Layout, str]:
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

    for text in texts:
        add(text)
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


def polygons(geom) -> list:
    if geom is None or geom.is_empty:
        return []
    return [geom] if geom.geom_type == "Polygon" else [g for g in getattr(geom, "geoms", []) if not g.is_empty]


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
    for geom in (layout.raised, layout.texture):
        for d in _poly_paths(geom):
            out.append(f'<path d="{d}" fill="black" fill-rule="evenodd"/>')
    if layout.corner:
        k = layout.corner
        out.append(f'<path d="M 0,{k:.2f} L {k:.2f},0" stroke="#9aa0a6" stroke-width="0.3" stroke-dasharray="1,1"/>')
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
def stl_with_volume(layout: Layout, spec: Spec | None = None) -> tuple[bytes, float]:
    """Watertight STL of plate + raised lines + braille domes; returns (bytes, volume mm^3)."""
    from manifold3d import CrossSection, Manifold, OpType
    import numpy as np
    import trimesh

    spec = spec or Spec()
    W, H, k = layout.width, layout.height, layout.corner
    outline = [(0, 0), (W, 0), (W, H), (k, H), (0, H - k)] if k else [(0, 0), (W, 0), (W, H), (0, H)]
    parts = [CrossSection([outline]).extrude(spec.plate_t)]

    def extrude(geom, height):
        for p in polygons(geom):
            rings = [[(x, H - y) for x, y in p.exterior.coords[:-1]]]
            rings += [[(x, H - y) for x, y in r.coords[:-1]] for r in p.interiors]
            parts.append(CrossSection(rings).extrude(height).translate([0, 0, spec.plate_t - 0.05]))

    extrude(layout.raised, spec.line_h)
    extrude(layout.texture, spec.line_h * 0.55)
    r = spec.dot_d / 2
    dome = Manifold.sphere(r, 20).scale([1, 1, spec.dot_h / r])
    for x, y in layout.dots:
        parts.append(dome.translate([x, H - y, spec.plate_t]))
    solid = Manifold.batch_boolean(parts, OpType.Add)
    mesh = solid.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
    buf = io.BytesIO()
    tm.export(buf, file_type="stl")
    return buf.getvalue(), float(solid.volume())


def to_stl(layout: Layout, spec: Spec | None = None) -> bytes:
    return stl_with_volume(layout, spec)[0]


# ---------------------------------------------------------------- export: PNG preview
def to_png(layout: Layout, spec: Spec | None = None, dpi: int = 120, style: str = "relief",
           show_ink: bool = True, pad: float = 1.5) -> bytes:
    """style='relief': raised parts lit from the top-left like a real embossed sheet.
    style='plan': flat black drawing. Blue ink = teacher-only annotations (never printed)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, PathPatch, Polygon as MPoly
    from matplotlib.path import Path as MPath

    spec = spec or Spec()
    W, H, k = layout.width, layout.height, layout.corner
    paper = "#f4f5f2" if style == "relief" else "white"
    fig, ax = plt.subplots(figsize=((W + 2 * pad) / 25.4, (H + 2 * pad) / 25.4), dpi=dpi)
    fig.patch.set_alpha(0)
    ax.set_xlim(-pad, W + pad)
    ax.set_ylim(H + pad, -pad)
    ax.set_aspect("equal")
    ax.axis("off")
    sheet = [(0, k), (k, 0), (W, 0), (W, H), (0, H)] if k else [(0, 0), (W, 0), (W, H), (0, H)]
    if style == "relief" and pad > 0:
        ax.add_patch(MPoly([(x + 0.8, y + 1.0) for x, y in sheet], closed=True, fc="#00000018", ec="none"))
    ax.add_patch(MPoly(sheet, closed=True, fc=paper, ec="#c9ccc4", lw=0.6))

    def path_of(p, dx=0.0, dy=0.0):
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            pts = [(x + dx, y + dy) for x, y in ring.coords]
            verts += pts
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 2) + [MPath.CLOSEPOLY]
        return MPath(verts, codes)

    layers = [(layout.raised, 1.0), (layout.texture, 0.6)]
    for geom, depth in layers:
        for p in polygons(geom):
            if style == "relief":
                ax.add_patch(PathPatch(path_of(p, 0.45 * depth, 0.55 * depth), fc="#8d9289", ec="none"))
                ax.add_patch(PathPatch(path_of(p, -0.25 * depth, -0.3 * depth), fc="#ffffff", ec="none"))
                ax.add_patch(PathPatch(path_of(p), fc="#dfe1da", ec="none"))
            else:
                ax.add_patch(PathPatch(path_of(p), fc="black", ec="none"))
    r = spec.dot_d / 2
    for x, y in layout.dots:
        if style == "relief":
            ax.add_patch(Circle((x + 0.3, y + 0.38), r, fc="#8d9289", ec="none"))
            ax.add_patch(Circle((x, y), r, fc="#e6e8e1", ec="none"))
            ax.add_patch(Circle((x - 0.28, y - 0.3), r * 0.45, fc="#ffffff", ec="none"))
        else:
            ax.add_patch(Circle((x, y), r, fc="black"))
    if show_ink:
        for text, x, y, size in layout.ink:
            ax.text(x, y, text, fontsize=size * 2.2, color="#2440c8", ha="left" if len(text) > 3 else "center",
                    va="bottom", family="DejaVu Sans")
    fig.subplots_adjust(0, 0, 1, 1)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    return buf.getvalue()
