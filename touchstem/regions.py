"""Any picture with parts -> tactile sheet + living sheet: floor plans, maps, biology and anatomy
diagrams, appliance control panels (printed 1:1 as an overlay).

Document (from the AI or an example):
{
  "title": "Второй этаж школы", "kind": "map" | "diagram" | "panel" | "other",
  "aspect": 1.6,                 # width / height of the source picture
  "width_mm": 90,                # optional: real width (panels -> overlay printed to scale)
  "regions": [{"id": "r1", "label": "Кабинет физики", "description": "...", "style": "room",
               "polygon": [[x, y], ...] | "box": [x0, y0, x1, y1] | "ellipse": [cx, cy, rx, ry],
               "braille": "1"}],                      # coordinates 0..1 (or 0..1000)
  "points": [{"label": "Вход", "kind": "entrance" | "stairs" | "you" | "other", "x": 0.5, "y": 0.98}]
}
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polylabel, unary_union

from .braille import translate
from .render import Layout, Spec, cells_size, place_cells

STYLES = ("room", "path", "object", "button", "area")
POINT_KINDS = ("entrance", "stairs", "you", "other")


class RegionError(ValueError):
    pass


@dataclass
class Region:
    id: str
    label: str
    description: str
    style: str
    poly: list[tuple[float, float]]
    braille: str = ""
    key: int | None = None


@dataclass
class MapPoint:
    label: str
    kind: str
    x: float
    y: float


@dataclass
class RegionDoc:
    title: str
    kind: str
    aspect: float
    regions: list[Region]
    points: list[MapPoint] = field(default_factory=list)
    width_mm: float | None = None
    notes: str = ""
    doors: list[tuple[float, float]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, lang: str = "ru") -> "RegionDoc":
        d = _localize(d, lang)
        if not isinstance(d, dict) or not d.get("regions"):
            raise RegionError("нет областей на рисунке")
        raw_regions = d["regions"]
        scale = 1000.0 if _max_coord(raw_regions, d.get("points", []) + [{"x": a, "y": b} for a, b in d.get("doors", []) or []]) > 1.5 else 1.0
        regions = []
        for i, r in enumerate(raw_regions):
            poly = _shape(r, scale)
            if len(poly) < 3:
                continue
            style = r.get("style", "object")
            regions.append(Region(str(r.get("id", f"r{i + 1}")), str(r.get("label", "") or f"область {i + 1}")[:60],
                                  str(r.get("description", "") or "")[:300],
                                  style if style in STYLES else "object", poly, str(r.get("braille", "") or "")[:6]))
        if not regions:
            raise RegionError("не удалось прочитать ни одной области")
        points = []
        for p in d.get("points", []) or []:
            try:
                points.append(MapPoint(str(p.get("label", ""))[:40], p.get("kind", "other") if p.get("kind") in POINT_KINDS
                                       else "other", float(p["x"]) / scale, float(p["y"]) / scale))
            except (KeyError, TypeError, ValueError):
                continue
        aspect = float(d.get("aspect") or 1.4)
        width = d.get("width_mm")
        doors = []
        for p in d.get("doors", []) or []:
            try:
                doors.append((float(p[0]) / scale, float(p[1]) / scale))
            except (TypeError, ValueError, IndexError):
                continue
        doc = cls(str(d.get("title", "") or ""), d.get("kind", "other"), max(0.3, min(aspect, 3.5)), regions, points,
                  float(width) if width else None, str(d.get("notes", "") or ""), doors[:40])
        # reading order: top to bottom, left to right
        for k, r in enumerate(sorted(doc.regions, key=lambda r: (round(_centroid(r.poly)[1] * 6), _centroid(r.poly)[0])), 1):
            r.key = k
        return doc


def _localize(v, lang):
    """Example files may hold {"ru": ..., "kk": ...} for any text field."""
    if isinstance(v, dict):
        if set(v) <= {"ru", "kk"} and v:
            return v.get(lang) or next(iter(v.values()))
        return {k: _localize(x, lang) for k, x in v.items()}
    if isinstance(v, list):
        return [_localize(x, lang) for x in v]
    return v


def _max_coord(regions, points) -> float:
    vals = []
    for r in regions:
        for k in ("polygon", "box", "ellipse"):
            v = r.get(k)
            if v:
                vals += [abs(c) for c in (sum(v, []) if k == "polygon" else v)]
    for p in points:
        vals += [abs(p.get("x", 0)), abs(p.get("y", 0))]
    return max(vals or [0])


def _shape(r: dict, scale: float) -> list[tuple[float, float]]:
    try:
        if r.get("polygon"):
            return [(float(x) / scale, float(y) / scale) for x, y in r["polygon"]][:40]
        if r.get("box"):
            x0, y0, x1, y1 = [float(v) / scale for v in r["box"]]
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if r.get("ellipse"):
            cx, cy, rx, ry = [float(v) / scale for v in r["ellipse"]]
            return [(cx + rx * math.cos(2 * math.pi * k / 28), cy + ry * math.sin(2 * math.pi * k / 28)) for k in range(28)]
    except (TypeError, ValueError):
        pass
    return []


def _centroid(poly):
    p = Polygon(poly)
    c = p.centroid if p.is_valid and p.area > 0 else Point(sum(x for x, _ in poly) / len(poly), sum(y for _, y in poly) / len(poly))
    return c.x, c.y


# ------------------------------------------------------------------ text
TR = {
    "ru": {"kind": {"map": "план", "diagram": "рисунок", "panel": "накладка на панель", "other": "рисунок"},
           "intro": "Это {kind}{title}. Срезанный угол — левый верхний. На листе {n} частей, их номера написаны шрифтом Брайля.",
           "where": {(0, 0): "вверху слева", (1, 0): "вверху по центру", (2, 0): "вверху справа",
                     (0, 1): "слева по центру", (1, 1): "в центре", (2, 1): "справа по центру",
                     (0, 2): "внизу слева", (1, 2): "внизу по центру", (2, 2): "внизу справа"},
           "tour": "{k} — {label}, {where}.", "near": "Рядом: {names}.", "inside": "Находится внутри: {name}.",
           "nonear": "Рядом ничего нет.", "point": "{label} — {where}.", "q_near": "Что находится рядом с {label}?",
           "q_where": "Где на листе {label}?", "q_count": "Сколько частей на листе?", "legend": "обозначения", "num": "номер {k}", "letter": "буква {b}",
           "points": {"entrance": "вход", "stairs": "лестница", "you": "вы здесь", "other": "точка"},
           "path_note": "Шероховатая область из точек — проход или коридор."},
    "kk": {"kind": {"map": "жоспар", "diagram": "сурет", "panel": "панельге жапсырма", "other": "сурет"},
           "intro": "Бұл {kind}{title}. Кесілген бұрышы — сол жақ жоғарғы бұрыш. Парақта {n} бөлік бар, нөмірлері Брайль қарпімен жазылған.",
           "where": {(0, 0): "жоғарғы сол жақта", (1, 0): "жоғарғы ортада", (2, 0): "жоғарғы оң жақта",
                     (0, 1): "сол жақ ортада", (1, 1): "ортада", (2, 1): "оң жақ ортада",
                     (0, 2): "төменгі сол жақта", (1, 2): "төменгі ортада", (2, 2): "төменгі оң жақта"},
           "tour": "{k} — {label}, {where}.", "near": "Жанында: {names}.", "inside": "Мынаның ішінде: {name}.",
           "nonear": "Жанында ештеңе жоқ.", "point": "{label} — {where}.", "q_near": "{label} жанында не орналасқан?",
           "q_where": "{label} парақтың қай жерінде?", "q_count": "Парақта неше бөлік бар?", "legend": "шартты белгілер", "num": "{k} нөмір", "letter": "{b} әрпі",
           "points": {"entrance": "кіреберіс", "stairs": "баспалдақ", "you": "сіз осындасыз", "other": "нүкте"},
           "path_note": "Нүктелі кедір-бұдыр аймақ — өтетін жол немесе дәліз."},
}


@dataclass
class RegionsResult:
    layout: Layout
    legend_lines: list[str]
    hotspots: list[dict]          # {"key", "label", "poly": [(x, y)...] mm, "l2", "l3", "area"}
    neighbors: dict
    doc: RegionDoc


def build_regions(doc: RegionDoc, spec: Spec | None = None, lang: str = "ru") -> RegionsResult:
    spec = spec or Spec()
    m = spec.margin
    if doc.width_mm:                                  # real size (overlay for a device)
        W = doc.width_mm + 2 * 6
        H = doc.width_mm / doc.aspect + 2 * 6
        m = 6
    else:
        W = spec.max_width
        H = (W - 2 * m) / doc.aspect + 2 * m
        if H > spec.max_height:
            H = spec.max_height
            W = (H - 2 * m) * doc.aspect + 2 * m
    iw, ih = W - 2 * m, H - 2 * m

    def P(x, y):
        return (m + x * iw, m + y * ih)

    polys = {r.id: Polygon([P(x, y) for x, y in r.poly]).buffer(0) for r in doc.regions}
    shapes, texture = [], []
    lw = spec.line_w / 2
    for r in doc.regions:
        poly = polys[r.id]
        if poly.is_empty:
            continue
        if r.style == "path":   # walkable area: dotted texture, no walls of its own
            minx, miny, maxx, maxy = poly.bounds
            y = miny + 2
            while y < maxy:
                x = minx + 2 + (2 if int((y - miny) / 4) % 2 else 0)
                while x < maxx:
                    pt = Point(x, y)
                    if poly.buffer(-2.2).contains(pt):
                        texture.append(pt.buffer(0.7, 10))
                    x += 4.0
                y += 4.0
            continue
        for ring in ([poly.exterior] if poly.geom_type == "Polygon" else [g.exterior for g in poly.geoms]):
            shapes.append(LineString(ring.coords).buffer(lw, join_style="round"))
    # points of interest
    for p in doc.points:
        x, y = P(p.x, p.y)
        if p.kind == "entrance":
            shapes.append(Polygon([(x - 4, y + 2.5), (x + 4, y + 2.5), (x, y - 4)]))
        elif p.kind == "stairs":
            for k in range(3):
                shapes.append(LineString([(x - 4, y - 3 + 3 * k), (x + 4, y - 3 + 3 * k)]).buffer(0.6, cap_style="flat"))
        elif p.kind == "you":
            shapes.append(Point(x, y).buffer(2.6))
        else:
            shapes.append(box(x - 2.2, y - 2.2, x + 2.2, y + 2.2))
    raised = unary_union(shapes) if shapes else Polygon()
    for dx, dy in doc.doors:                       # a door is a gap in the wall the finger can feel
        x, y = P(dx, dy)
        raised = raised.difference(Point(x, y).buffer(3.6))

    # braille labels: inside the region when it fits, otherwise the nearest free spot
    dots, ink, warnings = [], [], []
    obstacles = [raised.buffer(spec.label_gap * 0.75) if not raised.is_empty else Polygon()]
    frame = box(2, 2, W - 2, H - 2)
    for r in sorted(doc.regions, key=lambda r: r.key):
        text = r.braille or str(r.key)
        br = translate(text, lang)
        w, h = cells_size(len(br.cells), spec)
        poly = polys[r.id]
        if poly.is_empty:
            continue
        children = [polys[o.id] for o in doc.regions if o.id != r.id and polys[o.id].area < poly.area
                    and poly.contains(polys[o.id].representative_point())]
        own = poly.difference(unary_union(children)) if children else poly
        own = own if not own.is_empty else poly
        main = own if own.geom_type == "Polygon" else max(own.geoms, key=lambda g: g.area)
        try:
            anchor = polylabel(main, 0.5)
        except Exception:
            anchor = main.representative_point()
        cen = main.centroid
        if main.contains(cen) and main.exterior.distance(cen) >= 0.8 * main.exterior.distance(anchor):
            anchor = cen
        best = None
        for strict in (True, False):
            for radius in (0, 3, 6, 9, 12, 16, 22, 30):
                for ang in range(0, 360, 30 if radius else 360):
                    cx = anchor.x + radius * math.cos(math.radians(ang))
                    cy = anchor.y + radius * math.sin(math.radians(ang))
                    rect = box(cx - w / 2 - 0.6, cy - h / 2 - 0.6, cx + w / 2 + 0.6, cy + h / 2 + 0.6)
                    if strict and not own.contains(rect):
                        continue
                    if not frame.contains(rect) or any(rect.intersects(o) for o in obstacles):
                        continue
                    best = (cx, cy, rect)
                    break
                if best:
                    break
            if best:
                break
        if not best:
            warnings.append(f"для части {r.key} не хватило места под Брайль")
            continue
        cx, cy, rect = best
        dots += place_cells(br.cells, cx - w / 2, cy - h / 2, spec)
        obstacles.append(rect.buffer(1.5))
        ink.append((text, cx, cy - h / 2 - 2.2, 3.0))

    # neighbours (shared walls or within 4 mm), and containment
    t = TR[lang]
    neighbors: dict[str, dict] = {}
    for r in doc.regions:
        pr = polys[r.id]
        near, inside = [], None
        for o in doc.regions:
            if o.id == r.id:
                continue
            po = polys[o.id]
            if po.contains(pr.representative_point()) and po.area > pr.area:
                if inside is None or po.area < polys[inside.id].area:
                    inside = o
            elif pr.distance(po) < 4 and not pr.contains(po.representative_point()):
                near.append(o)
        neighbors[r.id] = {"near": near, "inside": inside}

    def where(poly) -> str:
        c = poly.centroid
        return t["where"][(min(2, int((c.x - m) / iw * 3)), min(2, int((c.y - m) / ih * 3)))]

    hotspots = []
    for r in sorted(doc.regions, key=lambda r: r.key):
        poly = polys[r.id]
        if poly.is_empty:
            continue
        nb = neighbors[r.id]
        l3 = []
        if nb["inside"]:
            l3.append(t["inside"].format(name=nb["inside"].label))
        l3.append(t["near"].format(names=", ".join(o.label for o in nb["near"][:5])) if nb["near"] else t["nonear"])
        main = poly if poly.geom_type == "Polygon" else max(poly.geoms, key=lambda g: g.area)
        hotspots.append({"key": r.key, "label": r.label, "where": where(poly),
                         "poly": [(round(x, 1), round(y, 1)) for x, y in list(main.exterior.coords)[:-1]],
                         "l2": r.description or where(poly), "l3": " ".join(l3), "area": round(main.area, 1)})
    for p in doc.points:   # points answer too
        x, y = P(p.x, p.y)
        name = p.label or t["points"][p.kind]
        ring = [(round(x + 6 * math.cos(a), 1), round(y + 6 * math.sin(a), 1)) for a in [k * math.pi / 6 for k in range(12)]]
        hotspots.append({"key": None, "label": name, "where": where(Point(x, y).buffer(1)), "poly": ring,
                         "l2": t["points"][p.kind], "l3": "", "area": 1.0})

    legend = [t["legend"]] + [f"{r.braille or r.key} {r.label}" for r in sorted(doc.regions, key=lambda r: r.key)]
    labels = unary_union(obstacles[1:]).buffer(2.0) if len(obstacles) > 1 else Polygon()
    texture = [d for d in texture if not d.intersects(labels)]
    lay = Layout(W, H, raised, dots, ink, warnings, texture=unary_union(texture) if texture else Polygon())
    lay.hotspots = [{"id": f"r{h['key']}", "key": h["key"], "type": "region",
                     "x": round(Polygon(h["poly"]).centroid.x, 1), "y": round(Polygon(h["poly"]).centroid.y, 1),
                     "r": 6.0} for h in hotspots]
    return RegionsResult(lay, legend, hotspots, neighbors, doc)


def regions_lesson(res: RegionsResult, lang: str = "ru"):
    from .lesson import Lesson
    t = TR[lang]
    doc = res.doc
    title = f" «{doc.title}»" if doc.title else ""
    intro = t["intro"].format(kind=t["kind"].get(doc.kind, t["kind"]["other"]), title=title, n=len(doc.regions))
    marks = {r.key: (t["letter"].format(b=r.braille) if r.braille and not r.braille.isdigit() else t["num"].format(k=r.braille or r.key))
             for r in doc.regions}
    tour = [t["tour"].format(k=marks[h["key"]][:1].upper() + marks[h["key"]][1:], label=h["label"], where=h["where"])
            for h in res.hotspots if h["key"]]
    tour += [t["point"].format(label=h["label"], where=h["where"]) for h in res.hotspots if not h["key"]]
    facts = []
    if any(r.style == "path" for r in doc.regions):
        facts.append(t["path_note"])
    facts += [f"{h['key']}. {h['label']}: {h['l2']}" for h in res.hotspots if h["key"] and h["l2"] != h["where"]][:8]
    quiz = []
    for h in [h for h in res.hotspots if h["key"]][:3]:
        nb = res.neighbors[next(r.id for r in doc.regions if r.key == h["key"])]["near"]
        if nb:
            quiz.append((t["q_near"].format(label=h["label"]), ", ".join(o.label for o in nb[:4])))
    for h in [h for h in res.hotspots if h["key"]][3:5]:
        quiz.append((t["q_where"].format(label=h["label"]), h["where"]))
    quiz.append((t["q_count"], str(len(doc.regions))))
    return Lesson(intro, tour, facts, quiz)
