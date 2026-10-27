"""Circuit element catalogue: names (ru/kk) and simplified tactile symbols.

Symbols are drawn in a local frame: u runs along the wire from -L/2 to +L/2,
v is perpendicular. Each symbol returns raised strokes (polylines), filled
shapes (polygons) and optional braille letters placed inside the symbol, so
look-alike symbols (ammeter vs voltmeter) feel different.
Kazakh terms should be confirmed with a teacher before classroom use.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

NAMES = {
    "wire":       {"ru": "провод",           "kk": "сым"},
    "resistor":   {"ru": "резистор",         "kk": "резистор"},
    "rheostat":   {"ru": "реостат",          "kk": "реостат"},
    "lamp":       {"ru": "лампа",            "kk": "шам"},
    "cell":       {"ru": "источник тока",    "kk": "ток көзі"},
    "battery":    {"ru": "батарея",          "kk": "батарея"},
    "switch":     {"ru": "ключ",             "kk": "кілт"},
    "capacitor":  {"ru": "конденсатор",      "kk": "конденсатор"},
    "ammeter":    {"ru": "амперметр",        "kk": "амперметр"},
    "voltmeter":  {"ru": "вольтметр",        "kk": "вольтметр"},
    "diode":      {"ru": "диод",             "kk": "диод"},
    "led":        {"ru": "светодиод",        "kk": "жарықдиод"},
    "fuse":       {"ru": "предохранитель",   "kk": "сақтандырғыш"},
    "motor":      {"ru": "электродвигатель", "kk": "электрқозғалтқыш"},
    "inductor":   {"ru": "катушка",          "kk": "катушка"},
    "other":      {"ru": "элемент",          "kk": "элемент"},
}
TYPES = tuple(NAMES)

LEGEND_TITLE = {"ru": "обозначения", "kk": "шартты белгілер"}


@dataclass
class Symbol:
    length: float                                   # extent along the wire, mm
    half_width: float                               # extent across the wire, mm
    strokes: list[list[tuple[float, float]]] = field(default_factory=list)
    fills: list[list[tuple[float, float]]] = field(default_factory=list)
    letters: list[tuple[str, float, float]] = field(default_factory=list)  # (cyrillic letter, u, v) centre
    gap: bool = False                                # True: no wire through the symbol body


def _circle(r: float, n: int = 48) -> list[tuple[float, float]]:
    pts = [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    return pts + [pts[0]]


def _rect(hl: float, hw: float) -> list[tuple[float, float]]:
    return [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw), (-hl, -hw)]


def symbol_for(kind: str) -> Symbol | None:
    if kind == "wire":
        return None
    if kind == "resistor":
        return Symbol(16, 3.5, strokes=[_rect(8, 3.5)], gap=True)
    if kind == "fuse":
        return Symbol(16, 3.5, strokes=[_rect(8, 3.5), [(-8, 0), (8, 0)]], gap=True)
    if kind == "rheostat":
        return Symbol(16, 6, strokes=[_rect(8, 3.5), [(-7, 6), (7, -6)]], gap=True)
    if kind == "inductor":
        pts = []
        for k in range(4):
            cx = -6 + 4 * k
            pts += [(cx - 2 + 4 * j / 12, -2 * math.sin(math.pi * j / 12)) for j in range(13)]
        return Symbol(16, 3, strokes=[pts], gap=True)
    if kind == "lamp":
        r, d = 6.0, 6.0 / math.sqrt(2)
        return Symbol(12, r, strokes=[_circle(r), [(-d, -d), (d, d)], [(-d, d), (d, -d)]], gap=True)
    if kind in ("ammeter", "voltmeter", "motor"):
        letter = {"ammeter": "а", "voltmeter": "в", "motor": "м"}[kind]
        return Symbol(14, 7, strokes=[_circle(7)], letters=[(letter, 0, 0)], gap=True)
    if kind == "cell":   # long plate = +, short thick plate = -
        return Symbol(4, 7, strokes=[[(-2, -7), (-2, 7)]], fills=[[(1.4, -3.5), (2.6, -3.5), (2.6, 3.5), (1.4, 3.5)]], gap=True)
    if kind == "battery":
        return Symbol(10, 7, strokes=[[(-5, -7), (-5, 7)], [(1, -7), (1, 7)]],
                      fills=[[(-2.6, -3.5), (-1.4, -3.5), (-1.4, 3.5), (-2.6, 3.5)],
                             [(3.4, -3.5), (4.6, -3.5), (4.6, 3.5), (3.4, 3.5)]], gap=True)
    if kind == "capacitor":
        return Symbol(4, 6, strokes=[[(-2, -6), (-2, 6)], [(2, -6), (2, 6)]], gap=True)
    if kind == "switch":
        pivot = [(x - 7, y) for x, y in _circle(1.4, 16)]
        contact = [(x + 7, y) for x, y in _circle(1.4, 16)]
        return Symbol(14, 6, strokes=[[(-7, 0), (6, 6)]], fills=[pivot, contact], gap=True)
    if kind in ("diode", "led"):
        sym = Symbol(12, 5, fills=[[(-4, -5), (4, 0), (-4, 5)]], strokes=[[(4, -5), (4, 5)]], gap=True)
        if kind == "led":
            sym.strokes += [[(1, 7), (5, 11)], [(-2, 7), (2, 11)]]
            sym.half_width = 11
        return sym
    return Symbol(10, 5, strokes=[_rect(5, 5)], gap=True)
