"""Function graphs: formula -> tactile axes, ticks, grid points, thick curve, braille numbers,
plus a spoken description computed from the function itself (zeros, extrema, monotonicity).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .braille import translate
from .render import Layout, Spec, cells_size, place_cells

ALLOWED_WORDS = {"x", "sin", "cos", "tan", "sqrt", "abs", "log", "ln", "exp", "pi", "e"}


class FormulaError(ValueError):
    pass


def clean_formula(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"^(y|f\s*\(\s*x\s*\))\s*=", "", s).strip()
    s = s.replace("^", "**").replace("√", "sqrt").replace("×", "*").replace("·", "*").replace("÷", "/")
    s = s.replace("−", "-").replace(",", ".")
    s = re.sub(r"\|([^|]+)\|", r"abs(\1)", s)
    if not s or len(s) > 80:
        raise FormulaError("формула пустая или слишком длинная")
    if not re.fullmatch(r"[0-9x+\-*/(). a-z]*", s):
        raise FormulaError("в формуле есть недопустимые символы")
    for word in re.findall(r"[a-z]+", s):
        if word not in ALLOWED_WORDS:
            raise FormulaError(f"неизвестное слово «{word}» — доступны x, sin, cos, tan, sqrt, abs, log, exp, pi")
    return s


def compile_formula(text: str):
    """Whitelisted input -> sympy expression -> numpy function."""
    import sympy as sp
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                            standard_transformations)
    s = clean_formula(text)
    x = sp.Symbol("x", real=True)
    local = {"x": x, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "sqrt": sp.sqrt, "abs": sp.Abs,
             "log": sp.log, "ln": sp.log, "exp": sp.exp, "pi": sp.pi, "e": sp.E}
    try:
        expr = parse_expr(s, local_dict=local, global_dict={"__builtins__": {}, **{k: getattr(sp, k) for k in
                          ("Integer", "Float", "Rational", "Symbol")}},
                          transformations=standard_transformations + (implicit_multiplication_application, convert_xor))
    except Exception as exc:
        raise FormulaError("не удалось разобрать формулу") from exc
    if expr.free_symbols - {x}:
        raise FormulaError("формула должна зависеть только от x")
    f = sp.lambdify(x, expr, modules=["numpy"])

    def safe(xs):
        with np.errstate(all="ignore"):
            ys = np.asarray(f(xs), dtype=float)
        if ys.shape == ():
            ys = np.full_like(xs, float(ys))
        ys[~np.isfinite(ys)] = np.nan
        return ys
    return expr, safe


def num(v: float) -> str:
    if abs(v) < 1e-6:
        return "0"
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


@dataclass
class Analysis:
    zeros: list[float] = field(default_factory=list)
    minima: list[tuple[float, float]] = field(default_factory=list)
    maxima: list[tuple[float, float]] = field(default_factory=list)
    y0: float | None = None
    pieces: list[tuple[float, float, str]] = field(default_factory=list)  # (x_from, x_to, 'up'|'down'|'flat')
    breaks: list[float] = field(default_factory=list)


def analyze(f, xmin: float, xmax: float, n: int = 4001) -> Analysis:
    xs = np.linspace(xmin, xmax, n)
    ys = f(xs)
    a = Analysis()
    if xmin <= 0 <= xmax:
        y0 = f(np.array([0.0]))[0]
        a.y0 = None if np.isnan(y0) else float(y0)
    span = np.nanmax(np.abs(ys)) if np.any(np.isfinite(ys)) else 1.0
    for i in range(n - 1):
        y1, y2 = ys[i], ys[i + 1]
        if np.isnan(y1) or np.isnan(y2):
            if np.isnan(y1) != np.isnan(y2):
                a.breaks.append(float(xs[i]))
            continue
        if abs(y2 - y1) > 0.5 * max(span, 1):
            a.breaks.append(float(xs[i]))
            continue
        if y1 == 0:
            a.zeros.append(float(xs[i]))
        elif y1 * y2 < 0:
            lo, hi = xs[i], xs[i + 1]
            for _ in range(50):
                mid = (lo + hi) / 2
                fm = f(np.array([mid]))[0]
                if np.isnan(fm):
                    break
                if f(np.array([lo]))[0] * fm <= 0:
                    hi = mid
                else:
                    lo = mid
            a.zeros.append(float((lo + hi) / 2))
    if ys[-1] == 0:
        a.zeros.append(float(xs[-1]))
    a.zeros = sorted(set(round(z, 4) for z in a.zeros))
    # monotonic pieces and extrema
    dy = np.diff(ys)
    tol = 1e-9 * max(span, 1)
    sign = np.where(np.isnan(dy), 0, np.where(dy > tol, 1, np.where(dy < -tol, -1, 0)))
    start = 0
    for i in range(1, len(sign) + 1):
        if i == len(sign) or sign[i] != sign[start]:
            kind = {1: "up", -1: "down", 0: "flat"}[int(sign[start])]
            if not (kind == "flat" and np.isnan(dy[start])):
                a.pieces.append((float(xs[start]), float(xs[i]), kind))
            if i < len(sign):
                if sign[start] == -1 and sign[i] == 1:
                    a.minima.append((float(xs[i]), float(ys[i])))
                if sign[start] == 1 and sign[i] == -1:
                    a.maxima.append((float(xs[i]), float(ys[i])))
            start = i
    merged: list[float] = []
    for b in sorted(a.breaks):
        if not merged or b - merged[-1] > (xmax - xmin) / 100:
            merged.append(b)
    a.breaks = merged
    # merge tiny pieces
    a.pieces = [p for p in a.pieces if p[1] - p[0] > (xmax - xmin) / 400]
    return a


TG = {
    "ru": {
        "legend": ["график функции", "горизонтальная ось от {x0} до {x1}", "вертикальная ось от {y0} до {y1}",
                   "точки сетки через {s}"],
        "zeros": "нули функции: {v}", "min": "наименьшее значение {y} при {x}", "max": "наибольшее значение {y} при {x}",
        "intro": "Это график функции{title}. Срезанный угол листа — левый верхний. Горизонтальная ось — от {x0} до {x1}, "
                 "вертикальная — от {y0} до {y1}. Толстая линия — график, тонкие линии со стрелками — оси, "
                 "мелкие точки — сетка через {s}.",
        "origin": "Найди точку, где пересекаются оси, — это начало координат, ноль.",
        "start": "Найди левый край толстой линии: график начинается {where}.",
        "up": "Веди палец вправо: график поднимается от {x0} до {x1}.",
        "down": "Веди палец вправо: график опускается от {x0} до {x1}.",
        "flat": "Дальше график идёт ровно от {x0} до {x1}.",
        "min_here": "Здесь самая низкая точка: при {x} значение {y}.",
        "max_here": "Здесь самая высокая точка: при {x} значение {y}.",
        "break": "Около {x} график прерывается — найди его продолжение правее.",
        "f_zeros": "График пересекает горизонтальную ось в точках: {v}.",
        "f_nozeros": "График не пересекает горизонтальную ось.",
        "f_y0": "Вертикальную ось график пересекает на высоте {y}.",
        "where": {"top": "вверху листа", "mid": "посередине по высоте", "bottom": "внизу листа"},
        "q_zeros": "Сколько раз график пересекает горизонтальную ось?",
        "q_min": "При каком x функция принимает наименьшее значение?",
        "q_max": "При каком x функция принимает наибольшее значение?",
        "q_y0": "На какой высоте график пересекает вертикальную ось?",
        "q_trend": "Функция возрастает или убывает в конце графика (справа)?",
        "a_up": "возрастает", "a_down": "убывает", "a_flat": "постоянна",
    },
    "kk": {
        "legend": ["функция графигі", "көлденең ось {x0}-ден {x1}-ге дейін", "тік ось {y0}-ден {y1}-ге дейін",
                   "тор нүктелері {s} сайын"],
        "zeros": "функцияның нөлдері: {v}", "min": "ең кіші мәні {y}, {x} нүктесінде",
        "max": "ең үлкен мәні {y}, {x} нүктесінде",
        "intro": "Бұл функция графигі{title}. Парақтың кесілген бұрышы — сол жақ жоғарғы бұрыш. Көлденең ось {x0}-ден "
                 "{x1}-ге дейін, тік ось {y0}-ден {y1}-ге дейін. Жуан сызық — график, жіңішке сызықтар — осьтер, "
                 "ұсақ нүктелер — {s} сайынғы тор.",
        "origin": "Осьтер қиылысатын нүктені тап — бұл координаталар басы, нөл.",
        "start": "Жуан сызықтың сол жақ шетін тап: график {where} басталады.",
        "up": "Саусағыңды оңға жүргіз: график {x0}-ден {x1}-ге дейін өседі.",
        "down": "Саусағыңды оңға жүргіз: график {x0}-ден {x1}-ге дейін кемиді.",
        "flat": "Әрі қарай график {x0}-ден {x1}-ге дейін түзу жүреді.",
        "min_here": "Мұнда ең төменгі нүкте: {x} нүктесінде мәні {y}.",
        "max_here": "Мұнда ең жоғарғы нүкте: {x} нүктесінде мәні {y}.",
        "break": "{x} маңында график үзіледі — оның жалғасын оң жақтан тап.",
        "f_zeros": "График көлденең осьті мына нүктелерде қиып өтеді: {v}.",
        "f_nozeros": "График көлденең осьті қиып өтпейді.",
        "f_y0": "График тік осьті {y} биіктікте қиып өтеді.",
        "where": {"top": "парақтың жоғарғы жағынан", "mid": "биіктіктің ортасынан", "bottom": "парақтың төменгі жағынан"},
        "q_zeros": "График көлденең осьті неше рет қиып өтеді?",
        "q_min": "x-тің қандай мәнінде функция ең кіші мәнін қабылдайды?",
        "q_max": "x-тің қандай мәнінде функция ең үлкен мәнін қабылдайды?",
        "q_y0": "График тік осьті қандай биіктікте қиып өтеді?",
        "q_trend": "Графиктің соңында (оң жақта) функция өседі ме, кемиді ме?",
        "a_up": "өседі", "a_down": "кемиді", "a_flat": "тұрақты",
    },
}


@dataclass
class GraphResult:
    layout: Layout
    legend_lines: list[str]
    analysis: Analysis
    step: float
    geom: dict = field(default_factory=dict)      # plate mapping for the living sheet
    samples: list = field(default_factory=list)   # y at 161 evenly spaced x (None where undefined)


def nice_step(span: float, unit_mm: float) -> float:
    for s in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        if s * unit_mm >= 8.0:
            return s
    return 100


def build_graph(formula: str, xr: tuple[float, float], yr: tuple[float, float], lang: str = "ru",
                spec: Spec | None = None) -> GraphResult:
    spec = spec or Spec()
    _, f = compile_formula(formula)
    (x0, x1), (y0, y1) = xr, yr
    if not (x1 > x0 and y1 > y0):
        raise FormulaError("неверные границы осей")
    warnings: list[str] = []
    left, right, top, bottom = spec.margin + 20, spec.margin + 8, spec.margin + 8, spec.margin + 12
    unit = min((spec.max_width - left - right) / (x1 - x0), (spec.max_height - top - bottom) / (y1 - y0))
    W = (x1 - x0) * unit + left + right
    H = (y1 - y0) * unit + top + bottom

    def X(x): return left + (x - x0) * unit
    def Y(y): return top + (y1 - y) * unit

    step = nice_step(max(x1 - x0, y1 - y0), unit)
    ax_y = 0.0 if y0 <= 0 <= y1 else y0          # where the horizontal axis sits
    ax_x = 0.0 if x0 <= 0 <= x1 else x0
    shapes, texture = [], []
    lw = spec.line_w / 2

    # axes with arrowheads at the positive ends
    shapes.append(LineString([(X(x0) - 2, Y(ax_y)), (X(x1) + 3, Y(ax_y))]).buffer(lw, cap_style="flat"))
    shapes.append(LineString([(X(ax_x), Y(y0) + 2), (X(ax_x), Y(y1) - 3)]).buffer(lw, cap_style="flat"))
    shapes.append(Polygon([(X(x1) + 3, Y(ax_y) - 3), (X(x1) + 8, Y(ax_y)), (X(x1) + 3, Y(ax_y) + 3)]))
    shapes.append(Polygon([(X(ax_x) - 3, Y(y1) - 3), (X(ax_x), Y(y1) - 8), (X(ax_x) + 3, Y(y1) - 3)]))

    ticks_x = [k * step for k in range(math.ceil(x0 / step), math.floor(x1 / step) + 1)]
    ticks_y = [k * step for k in range(math.ceil(y0 / step), math.floor(y1 / step) + 1)]
    for t in ticks_x:
        if abs(t - ax_x) > 1e-9:
            shapes.append(LineString([(X(t), Y(ax_y) - 2.5), (X(t), Y(ax_y) + 2.5)]).buffer(lw * 0.8, cap_style="flat"))
    for t in ticks_y:
        if abs(t - ax_y) > 1e-9:
            shapes.append(LineString([(X(ax_x) - 2.5, Y(t)), (X(ax_x) + 2.5, Y(t))]).buffer(lw * 0.8, cap_style="flat"))

    # curve
    xs = np.linspace(x0, x1, 1600)
    ys = f(xs)
    segs, cur = [], []
    for xv, yv in zip(xs, ys):
        ok = not np.isnan(yv) and y0 - 0.5 * step <= yv <= y1 + 0.5 * step
        if ok and cur and abs(yv - cur[-1][1]) > (y1 - y0) / 4:
            ok_break = True
        else:
            ok_break = False
        if not ok or ok_break:
            if len(cur) > 1:
                segs.append(cur)
            cur = [(xv, yv)] if ok_break else []
            continue
        cur.append((xv, yv))
    if len(cur) > 1:
        segs.append(cur)
    frame = box(X(x0), Y(y1), X(x1), Y(y0))
    curve_geoms = []
    for sgm in segs:
        line = LineString([(X(a), Y(b)) for a, b in sgm]).simplify(0.15)
        curve_geoms.append(line.buffer(1.0, cap_style="round").intersection(frame.buffer(1.0)))
    if not curve_geoms:
        warnings.append("график не попадает в выбранные границы — измените диапазон осей")
    curve = unary_union(curve_geoms) if curve_geoms else Polygon()

    raised = unary_union(shapes + [curve])
    # braille numbers: x below the axis, y left of the axis
    dots, ink = [], []
    label_rects: list = []
    obstacles = [raised.buffer(spec.label_gap)]

    def place(text, cx, cy):
        br = translate(text, lang)
        w, h = cells_size(len(br.cells), spec)
        rect = box(cx - w / 2 - 1, cy - h / 2 - 1, cx + w / 2 + 1, cy + h / 2 + 1)
        if any(rect.intersects(o) for o in obstacles) or rect.difference(box(0, 0, W, H)).area > 0:
            return False
        dots.extend(place_cells(br.cells, cx - w / 2, cy - h / 2, spec))
        obstacles.append(rect.buffer(2))
        label_rects.append(rect)
        ink.append((text, cx, cy - h / 2 - 2.2, 3.0))
        return True

    def label_every(ticks):
        widest = max((cells_size(len(translate(num(t), lang).cells), spec)[0] for t in ticks), default=0)
        k = 1
        while k * step * unit < widest + 4:
            k += 1
        return k

    off_y = 2.5 + spec.label_gap + spec.dot_pitch + 2.5
    kx = label_every(ticks_x)
    for i, t in enumerate(ticks_x):
        if abs(t) < 1e-9 or round(t / step) % kx:
            continue
        for dy in (off_y, -off_y):
            if place(num(t), X(t), Y(ax_y) + dy):
                break
    ky = max(1, math.ceil((2 * spec.dot_pitch + 4) / (step * unit)))
    for t in ticks_y:
        if abs(t) < 1e-9 or round(t / step) % ky:
            continue
        w = cells_size(len(translate(num(t), lang).cells), spec)[0]
        off_x = 2.5 + spec.label_gap + w / 2 + 1.5
        for dx in (-off_x, off_x):
            if place(num(t), X(ax_x) + dx, Y(t)):
                break
    for cx, cy in [(X(ax_x) + sx * dx, Y(ax_y) + sy * off_y) for dx in (8, 12, 16) for sx in (-1, 1) for sy in (1, -1)]:
        if place("0", cx, cy):
            break

    # grid points (texture), not on axes and away from the curve
    for tx in ticks_x:
        for ty in ticks_y:
            if abs(tx - ax_x) < 1e-9 or abs(ty - ax_y) < 1e-9:
                continue
            p = Point(X(tx), Y(ty))
            if not curve.is_empty and curve.distance(p) < 2.5:
                continue
            if any(r.distance(p) < 2.5 for r in label_rects):
                continue
            texture.append(p.buffer(0.75, 12))

    a = analyze(f, x0, x1)
    t = TG[lang]
    legend = [t["legend"][0], t["legend"][1].format(x0=num(x0), x1=num(x1)),
              t["legend"][2].format(y0=num(y0), y1=num(y1)), t["legend"][3].format(s=num(step))]
    if a.zeros:
        legend.append(t["zeros"].format(v="; ".join(num(z) for z in a.zeros[:6])))
    for xm, ym in a.minima[:2]:
        legend.append(t["min"].format(x=num(xm), y=num(ym)))
    for xm, ym in a.maxima[:2]:
        legend.append(t["max"].format(x=num(xm), y=num(ym)))
    lay = Layout(W, H, raised, dots, ink, warnings, texture=unary_union(texture) if texture else Polygon())
    sx = np.linspace(x0, x1, 161)
    sy = f(sx)
    samples = [None if np.isnan(v) else round(float(v), 3) for v in sy]
    geom = {"left": left, "top": top, "unit": unit, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "ax_x": ax_x, "ax_y": ax_y}
    return GraphResult(lay, legend, a, step, geom, samples)


def graph_lesson(formula: str, xr, yr, res: GraphResult, lang: str = "ru", title: str = ""):
    from .lesson import Lesson
    t = TG[lang]
    a = res.analysis
    (x0, x1), (y0, y1) = xr, yr
    intro = t["intro"].format(title=f" «{title}»" if title else "", x0=num(x0), x1=num(x1), y0=num(y0), y1=num(y1),
                              s=num(res.step))
    tour = [t["origin"]]
    _, f = compile_formula(formula)
    first = next((p for p in a.pieces), None)
    if first:
        yv = f(np.array([first[0] + 1e-6]))[0]
        if not np.isnan(yv):
            rel = (yv - y0) / (y1 - y0)
            where = "top" if rel > 0.66 else "bottom" if rel < 0.33 else "mid"
            tour.append(t["start"].format(where=t["where"][where]))
    extrema = {round(x, 3): ("min", x, y) for x, y in a.minima}
    extrema.update({round(x, 3): ("max", x, y) for x, y in a.maxima})
    for xa, xb, kind in a.pieces[:8]:
        tour.append(t[kind].format(x0=num(xa), x1=num(xb)))
        hit = extrema.get(round(xb, 3))
        if hit:
            tour.append(t["min_here" if hit[0] == "min" else "max_here"].format(x=num(hit[1]), y=num(hit[2])))
    for b in a.breaks[:3]:
        tour.append(t["break"].format(x=num(b)))
    facts = [t["f_zeros"].format(v="; ".join(num(z) for z in a.zeros)) if a.zeros else t["f_nozeros"]]
    if a.y0 is not None:
        facts.append(t["f_y0"].format(y=num(a.y0)))
    quiz = [(t["q_zeros"], str(len(a.zeros)))]
    if a.minima:
        quiz.append((t["q_min"], num(min(a.minima, key=lambda p: p[1])[0])))
    if a.maxima:
        quiz.append((t["q_max"], num(max(a.maxima, key=lambda p: p[1])[0])))
    if a.y0 is not None:
        quiz.append((t["q_y0"], num(a.y0)))
    if a.pieces:
        quiz.append((t["q_trend"], t["a_" + a.pieces[-1][2]]))
    return Lesson(intro, tour, facts, quiz)
