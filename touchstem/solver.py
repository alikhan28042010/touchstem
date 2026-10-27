"""DC circuit solver (modified nodal analysis) for school circuits.

Conventions
  * cell / battery: "from" node is the + terminal (long plate), EMF from value ("4,5 В").
  * resistor, lamp, rheostat, fuse, motor: resistance from value ("10 Ом"); a lamp may
    instead carry its rating ("6 В 0,5 А") -> R = U / I.
  * wire, closed switch, inductor: ideal conductors (nodes are merged).
  * ammeter: ideal (0 Ом, current measured). voltmeter: ideal (open, voltage measured).
  * open switch, capacitor: open circuit in DC.
  * diode / LED / other without a resistance: cannot be solved -> reported, not guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .model import Circuit

PREFIX = {"мк": 1e-6, "µ": 1e-6, "u": 1e-6, "м": 1e-3, "m": 1e-3, "к": 1e3, "k": 1e3, "М": 1e6, "M": 1e6, "": 1.0}
QTY_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*(мк|µ|м|к|М|)\s*(Ом|В|А|Вт|Ф)(?![а-яё])")

RESISTIVE = {"resistor", "lamp", "rheostat", "fuse", "motor"}
CONDUCTOR = {"wire", "inductor"}
SOURCES = {"cell", "battery"}


def quantities(text: str) -> dict[str, float]:
    """'6 В 0,5 А' -> {'В': 6.0, 'А': 0.5}. 'м' before 'Ом' would be ambiguous, so 'мОм' is not supported."""
    out: dict[str, float] = {}
    for num, pre, unit in QTY_RE.findall(text or ""):
        out[unit] = float(num.replace(",", ".")) * PREFIX[pre]
    return out


@dataclass
class ElementResult:
    voltage: float | None = None   # V(from) - V(to)
    current: float | None = None   # from -> to through the element
    power: float | None = None


@dataclass
class Solution:
    ok: bool
    results: dict[str, ElementResult] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)   # element ids lacking values
    short_circuit: list[str] = field(default_factory=list)
    source_current: float | None = None
    total_resistance: float | None = None
    message: str = ""


class _DSU:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def resistance_of(kind: str, value: str) -> float | None:
    q = quantities(value)
    if "Ом" in q and q["Ом"] > 0:
        return q["Ом"]
    if kind == "lamp" and q.get("В") and q.get("А"):
        return q["В"] / q["А"]
    return None


def solve(c: Circuit) -> Solution:
    els = c.elements
    dsu = _DSU(c.nodes)
    for e in els:
        if e.type in CONDUCTOR or (e.type == "switch" and e.state == "closed"):
            dsu.union(e.a, e.b)

    missing, shorts = [], []
    resist, vsrc = [], []   # (element, R) ; (element, E)
    for e in els:
        a, b = dsu.find(e.a), dsu.find(e.b)
        if e.type in SOURCES:
            emf = quantities(e.value).get("В")
            if emf is None:
                missing.append(e.id)
            elif a == b:
                shorts.append(e.id)
            else:
                vsrc.append((e, emf))
        elif e.type == "ammeter":
            if a != b:
                vsrc.append((e, 0.0))
        elif e.type in RESISTIVE:
            r = resistance_of(e.type, e.value)
            if r is None:
                missing.append(e.id)
            elif a != b:
                resist.append((e, r))
        elif e.type in ("diode", "led", "other"):
            missing.append(e.id)

    if shorts:
        return Solution(False, missing=missing, short_circuit=shorts,
                        message="Короткое замыкание: выводы источника соединены проводом напрямую.")
    if not any(e.type in SOURCES for e, _ in vsrc):
        return Solution(False, missing=missing, message="Нужен источник с напряжением (например «4,5 В»).")
    if missing:
        return Solution(False, missing=missing, message="Не у всех элементов указаны значения — расчёт недоступен.")

    first_src = next(e for e, _ in vsrc if e.type in SOURCES)
    ground = dsu.find(first_src.b)
    supernodes = sorted({dsu.find(n) for n in c.nodes} - {ground})
    idx = {n: i for i, n in enumerate(supernodes)}
    N, M = len(supernodes), len(vsrc)
    A = np.zeros((N + M, N + M))
    z = np.zeros(N + M)
    for i in range(N):
        A[i, i] += 1e-12  # gmin keeps floating sections solvable
    for e, r in resist:
        g = 1.0 / r
        a, b = dsu.find(e.a), dsu.find(e.b)
        for x, y, s in ((a, a, g), (b, b, g), (a, b, -g), (b, a, -g)):
            if x in idx and y in idx:
                A[idx[x], idx[y]] += s
    for k, (e, emf) in enumerate(vsrc):
        a, b = dsu.find(e.a), dsu.find(e.b)
        row = N + k
        if a in idx:
            A[idx[a], row] += 1
            A[row, idx[a]] += 1
        if b in idx:
            A[idx[b], row] -= 1
            A[row, idx[b]] -= 1
        z[row] = emf
    try:
        x = np.linalg.solve(A, z)
    except np.linalg.LinAlgError:
        return Solution(False, message="Схему не удалось рассчитать: проверьте соединения.")

    def V(node: str) -> float:
        s = dsu.find(node)
        return 0.0 if s == ground else float(x[idx[s]])

    res: dict[str, ElementResult] = {}
    src_current = {}
    for k, (e, emf) in enumerate(vsrc):
        i_branch = -float(x[N + k])  # MNA current enters + node; flip to "out of + terminal"
        if e.type in SOURCES:
            src_current[e.id] = i_branch
            res[e.id] = ElementResult(emf, i_branch, emf * i_branch)
        else:  # ammeter: current from 'from' to 'to'
            res[e.id] = ElementResult(0.0, -i_branch, 0.0)
    for e, r in resist:
        u = V(e.a) - V(e.b)
        res[e.id] = ElementResult(u, u / r, u * u / r)
    for e in els:
        if e.id in res:
            continue
        u = V(e.a) - V(e.b)
        if e.type == "voltmeter":
            res[e.id] = ElementResult(u, 0.0, 0.0)
        elif e.type in ("capacitor",) or (e.type == "switch" and e.state == "open"):
            res[e.id] = ElementResult(u, 0.0, 0.0)
        elif e.type in RESISTIVE:  # shorted by a wire
            res[e.id] = ElementResult(0.0, 0.0, 0.0)
    def clean(v):
        return 0.0 if v is not None and abs(v) < 1e-7 else v

    for r in res.values():
        r.voltage, r.current, r.power = clean(r.voltage), clean(r.current), clean(r.power)
    src_current = {k: clean(v) for k, v in src_current.items()}
    main_i = src_current.get(first_src.id)
    emf0 = res[first_src.id].voltage
    total_r = emf0 / main_i if main_i and abs(main_i) > 1e-9 else None
    return Solution(True, res, source_current=main_i, total_resistance=total_r)


def fmt(value: float | None, unit: str, lang: str = "ru") -> str:
    """5.0 'В' -> '5 В'; 0.0333 'А' -> '33 мА'; comma decimal separator."""
    if value is None:
        return "—"
    v = abs(value)
    prefixes = [(1e6, "М"), (1e3, "к"), (1, ""), (1e-3, "м"), (1e-6, "мк")]
    scale, pre = 1, ""
    if v > 0:
        for s, p in prefixes:
            if v >= s * 0.9999:
                scale, pre = s, p
                break
        else:
            scale, pre = 1e-6, "мк"
    from decimal import ROUND_HALF_UP, Decimal
    num = float(f"{value / scale:.9g}")            # kill binary noise: 187.4999999 -> 187.5
    d = Decimal(repr(num))
    digits = 3 - (d.adjusted() + 1)                 # three significant figures, half-up
    q = d.quantize(Decimal(1).scaleb(-max(digits, 0)), rounding=ROUND_HALF_UP) if digits > 0 else \
        d.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    txt = format(q.normalize(), "f")
    return f"{txt.replace('.', ',')} {pre}{unit}"
