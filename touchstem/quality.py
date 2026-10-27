"""Tactile readability check: rules a tactile-graphics specialist applies by hand.

Thresholds are conservative defaults (≈3 mm between separate lines, braille kept
away from lines, low clutter, few symbols per sheet, size that fits common
printers and A4 swell paper). The score is a checklist summary, not a guarantee:
the real test is a student reading the sheet.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point
from shapely.strtree import STRtree

from .render import Layout, Spec, polygons

PLA_DENSITY = 1.24  # g/cm^3


@dataclass
class Check:
    name: str
    status: str      # "ok" | "warn" | "fail"
    detail: str


@dataclass
class Report:
    score: int
    checks: list[Check]


def check_layout(layout: Layout, spec: Spec | None = None, n_symbols: int = 0,
                 extra_warnings: list[str] | None = None, lang: str = "ru") -> Report:
    spec = spec or Spec()
    checks: list[Check] = []

    # 1. separate raised lines must be far enough apart to feel as two
    polys = polygons(layout.raised)
    tree = STRtree(polys)
    close = 0
    worst = None
    for i, p in enumerate(polys):
        for j in tree.query(p.buffer(3.0)):
            if j <= i:
                continue
            d = p.distance(polys[j])
            if d < 3.0:
                close += 1
                worst = d if worst is None else min(worst, d)
    if close == 0:
        checks.append(Check("Расстояние между линиями", "ok", "все отдельные линии не ближе 3 мм друг к другу"))
    else:
        checks.append(Check("Расстояние между линиями", "fail" if worst < 2.0 else "warn",
                            f"{close} мест(а), где линии ближе 3 мм (минимум {worst:.1f} мм) — пальцы сольют их в одну"))

    # 2. braille dots clear of lines
    min_clear = None
    for x, y in layout.dots:
        d = layout.raised.distance(Point(x, y)) - spec.dot_d / 2 if not layout.raised.is_empty else 99
        if d < 0.05:   # dots placed inside a symbol on purpose (meter letters) are separate from lines
            continue
        min_clear = d if min_clear is None else min(min_clear, d)
    if min_clear is None or min_clear >= 2.5:
        checks.append(Check("Брайль не касается линий", "ok", "точки Брайля отделены от линий"))
    else:
        checks.append(Check("Брайль не касается линий", "warn" if min_clear >= 1.5 else "fail",
                            f"точки Брайля в {min_clear:.1f} мм от линии — легко спутать"))

    # 3. clutter
    area = layout.width * layout.height
    raised_area = layout.raised.area + layout.texture.area + len(layout.dots) * 3.14 * (spec.dot_d / 2) ** 2
    density = raised_area / area if area else 0
    if density <= 0.12:
        checks.append(Check("Плотность рельефа", "ok", f"рельеф занимает {density:.0%} листа — не перегружено"))
    else:
        checks.append(Check("Плотность рельефа", "warn" if density <= 0.2 else "fail",
                            f"рельеф занимает {density:.0%} листа — лист перегружен, упростите или разделите"))

    # 4. number of symbols
    if n_symbols <= 10:
        checks.append(Check("Количество символов", "ok", f"{n_symbols} обозначений — легко запомнить"))
    else:
        checks.append(Check("Количество символов", "warn" if n_symbols <= 15 else "fail",
                            f"{n_symbols} обозначений — лучше разбить на 2 листа"))

    # 5. physical size
    fits_bed = layout.width <= 220 and layout.height <= 220
    fits_a4 = (layout.width <= 297 and layout.height <= 210) or (layout.width <= 210 and layout.height <= 297)
    if fits_bed and fits_a4:
        checks.append(Check("Размер листа", "ok", f"{layout.width:.0f}×{layout.height:.0f} мм — помещается на 3D-принтер и лист A4"))
    else:
        checks.append(Check("Размер листа", "warn",
                            f"{layout.width:.0f}×{layout.height:.0f} мм — " +
                            ("не помещается на стол 220×220 мм" if not fits_bed else "больше листа A4")))

    # 6. warnings from parsing / layout / braille
    w = [x for x in (extra_warnings or []) + layout.warnings]
    if not w:
        checks.append(Check("Подписи и разметка", "ok", "подписи размещены без конфликтов"))
    else:
        checks.append(Check("Подписи и разметка", "warn", "; ".join(dict.fromkeys(w))[:300]))

    score = 100
    for ch in checks:
        score -= {"ok": 0, "warn": 6, "fail": 18}[ch.status]
    return Report(max(score, 0), checks)


@dataclass
class PrintEstimate:
    grams: float
    cost_tenge: float
    minutes: float


def print_estimate(volume_mm3: float, price_per_kg: float = 9000.0, grams_per_hour: float = 20.0,
                   fill: float = 0.9) -> PrintEstimate:
    """Thin plates print almost solid; fill≈0.9. Speed varies a lot by printer, so time is approximate."""
    grams = volume_mm3 / 1000 * PLA_DENSITY * fill
    return PrintEstimate(grams, grams * price_per_kg / 1000, grams / grams_per_hour * 60)
