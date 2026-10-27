"""Living sheet: the printed plate answers when it is touched.

A phone camera looks at the plate lying on a paper mat with four ArUco markers.
Because TouchSTEM generated the plate, every element's position is already known:
no manual labelling. Touch an element once -> its name; tap again -> live values
from the circuit solver; tap a switch again -> the circuit is re-simulated and the
phone announces what changed (lamps go dark, meters change).

This module builds the compact payload for static/touch.js and the printable mat.
"""
from __future__ import annotations

import copy
import io
import json
from itertools import product
from pathlib import Path

from .components import NAMES
from .model import Circuit
from .render import Layout, Spec, to_svg
from .share import _pack
from .solver import fmt, solve

MAT_W, MAT_H = 297.0, 210.0          # A4 landscape
MARKER, MARGIN = 30.0, 10.0          # black square side, distance from the paper edge
MAX_SWITCHES = 3

_MARKERS = json.loads((Path(__file__).with_name("markers.json")).read_text(encoding="utf-8"))


def marker_layout() -> list[list[float]]:
    """[id, centre_x, centre_y, side] in mat millimetres; ids 1..4 = TL, TR, BR, BL."""
    c = MARGIN + MARKER / 2
    return [[1, c, c, MARKER], [2, MAT_W - c, c, MARKER], [3, MAT_W - c, MAT_H - c, MARKER], [4, c, MAT_H - c, MARKER]]


def plate_offset(layout: Layout) -> tuple[float, float]:
    return ((MAT_W - layout.width) / 2, (MAT_H - layout.height) / 2)


def fits_mat(layout: Layout) -> bool:
    free_w = MAT_W - 2 * (MARGIN + MARKER + 4)
    return layout.width <= free_w and layout.height <= MAT_H - 8


UNIT_WORDS = [("мкФ", "микрофарад"), ("кОм", "килоом"), ("МОм", "мегаом"), ("Ом", "ом"), ("мВ", "милливольт"),
              ("кВ", "киловольт"), ("В", "вольт"), ("мкА", "микроампер"), ("мА", "миллиампер"), ("А", "ампер"),
              ("мВт", "милливатт"), ("кВт", "киловатт"), ("Вт", "ватт")]


def say(value: float | None, unit: str) -> str:
    """Speakable value: 0.188 A -> '188 миллиампер' (units as words so phone voices read them right)."""
    text = fmt(abs(value) if value is not None else None, unit)
    num, _, u = text.partition(" ")
    for short, word in UNIT_WORDS:
        if u == short:
            return f"{num} {word}"
    return text


TX = {
    "ru": {
        "l1": "номер {k}, {name}", "junction": "развилка, здесь провод делится",
        "load": "напряжение {u}, ток {i}", "lamp_off": "лампа не горит", "ammeter": "показывает {i}",
        "voltmeter": "показывает {u}", "source": "даёт {u}, ток от источника {i}",
        "sw_closed": "ключ замкнут. Коснитесь ещё раз, чтобы разомкнуть",
        "sw_open": "ключ разомкнут. Коснитесь ещё раз, чтобы замкнуть",
        "nosolve": "для расчёта нужны значения элементов", "short": "короткое замыкание!",
        "remove": "если убрать этот элемент, ток от источника станет {i}",
        "now_open": "Ключ {k} разомкнут.", "now_closed": "Ключ {k} замкнут.",
        "went_off": "Лампа {k} погасла.", "went_on": "Лампа {k} загорелась.",
        "brighter": "Лампа {k} стала ярче.", "dimmer": "Лампа {k} стала тусклее.",
        "amm_now": "Амперметр {k} теперь показывает {i}.", "volt_now": "Вольтметр {k} теперь показывает {u}.",
        "src_now": "Ток от источника {i}.", "nothing": "В цепи ничего не изменилось.",
        "g_point": "икс {x}, игрек {y}", "g_zero": "здесь график пересекает горизонтальную ось",
        "g_min": "самая низкая точка", "g_max": "самая высокая точка", "g_axis_x": "горизонтальная ось",
        "g_axis_y": "вертикальная ось", "g_origin": "начало координат",
    },
    "kk": {
        "l1": "{k} нөмір, {name}", "junction": "тармақталу нүктесі, мұнда сым бөлінеді",
        "load": "кернеу {u}, ток {i}", "lamp_off": "шам жанбайды", "ammeter": "{i} көрсетеді",
        "voltmeter": "{u} көрсетеді", "source": "{u} береді, ток көзінен шығатын ток {i}",
        "sw_closed": "кілт тұйықталған. Ажырату үшін тағы бір рет түртіңіз",
        "sw_open": "кілт ажыратулы. Тұйықтау үшін тағы бір рет түртіңіз",
        "nosolve": "есептеу үшін элементтердің мәндері керек", "short": "қысқа тұйықталу!",
        "remove": "бұл элементті алып тастаса, ток көзінен шығатын ток {i} болады",
        "now_open": "{k} кілт ажыратылды.", "now_closed": "{k} кілт тұйықталды.",
        "went_off": "{k} шам сөнді.", "went_on": "{k} шам жанды.",
        "brighter": "{k} шам жарығырақ жанады.", "dimmer": "{k} шам күңгірттенді.",
        "amm_now": "{k} амперметр енді {i} көрсетеді.", "volt_now": "{k} вольтметр енді {u} көрсетеді.",
        "src_now": "Ток көзінен шығатын ток {i}.", "nothing": "Тізбекте ештеңе өзгерген жоқ.",
        "g_point": "икс {x}, игрек {y}", "g_zero": "мұнда график көлденең осьті қиып өтеді",
        "g_min": "ең төменгі нүкте", "g_max": "ең жоғарғы нүкте", "g_axis_x": "көлденең ось",
        "g_axis_y": "тік ось", "g_origin": "координаталар басы",
    },
}


def _with_states(c: Circuit, switches: list[str], mask: int) -> Circuit:
    alt = copy.deepcopy(c)
    for bit, sid in enumerate(switches):
        el = next(e for e in alt.elements if e.id == sid)
        el.state = "closed" if mask >> bit & 1 else "open"
    return alt


def _l2(e, sol, t) -> str:
    if sol.short_circuit:
        return t["short"]
    if not sol.ok:
        return t["nosolve"]
    r = sol.results.get(e.id)
    if r is None:
        return ""
    if e.type == "ammeter":
        return t["ammeter"].format(i=say(r.current, "А"))
    if e.type == "voltmeter":
        return t["voltmeter"].format(u=say(r.voltage, "В"))
    if e.type in ("cell", "battery"):
        return t["source"].format(u=say(r.voltage, "В"), i=say(sol.source_current, "А"))
    if e.type == "lamp" and abs(r.current or 0) < 1e-6:
        return t["lamp_off"]
    return t["load"].format(u=say(r.voltage, "В"), i=say(r.current, "А"))


def _diff(c: Circuit, before, after, sw_key: int, now_closed: bool, t) -> str:
    parts = [(t["now_closed"] if now_closed else t["now_open"]).format(k=sw_key)]
    if not (before.ok and after.ok):
        parts.append(t["short"] if after.short_circuit else t["nosolve"])
        return " ".join(parts)
    changed = False
    for e in sorted((e for e in c.elements if e.key), key=lambda e: e.key):
        a, b = before.results.get(e.id), after.results.get(e.id)
        if not a or not b:
            continue
        if e.type == "lamp":
            pa, pb = abs(a.power or 0), abs(b.power or 0)
            if pa > 1e-6 and pb <= 1e-6:
                parts.append(t["went_off"].format(k=e.key)); changed = True
            elif pa <= 1e-6 and pb > 1e-6:
                parts.append(t["went_on"].format(k=e.key)); changed = True
            elif pa > 1e-6 and abs(pb - pa) / pa > 0.1:
                parts.append(t["brighter" if pb > pa else "dimmer"].format(k=e.key)); changed = True
        elif e.type == "ammeter" and abs((a.current or 0) - (b.current or 0)) > 1e-6:
            parts.append(t["amm_now"].format(k=e.key, i=say(b.current, "А"))); changed = True
        elif e.type == "voltmeter" and abs((a.voltage or 0) - (b.voltage or 0)) > 1e-6:
            parts.append(t["volt_now"].format(k=e.key, u=say(b.voltage, "В"))); changed = True
    if abs((before.source_current or 0) - (after.source_current or 0)) > 1e-6:
        parts.append(t["src_now"].format(i=say(after.source_current, "А")))
    elif not changed:
        parts.append(t["nothing"])
    return " ".join(parts)


def circuit_payload(c: Circuit, layout: Layout, lang: str = "ru") -> dict:
    t = TX[lang]
    switches = [e.id for e in c.elements if e.type == "switch"][:MAX_SWITCHES]
    n_states = 1 << len(switches)
    init = sum(1 << b for b, sid in enumerate(switches) if next(e for e in c.elements if e.id == sid).state == "closed")
    sols = {m: solve(_with_states(c, switches, m)) for m in range(n_states)}
    by_id = {e.id: e for e in c.elements}
    hs, sw_index = [], []
    for h in layout.hotspots:
        if h["type"] == "junction":
            hs.append([h["x"], h["y"], h["r"], None, None, t["junction"], [], [], []])
            continue
        e = by_id[h["id"]]
        l1 = t["l1"].format(k=e.key, name=NAMES[e.type][lang])
        l2, l3 = [], []
        for m in range(n_states):
            s = sols[m]
            if e.type == "switch" and e.id in switches:
                closed = bool(m >> switches.index(e.id) & 1)
                l2.append(t["sw_closed"] if closed else t["sw_open"])
                l3.append("")
                continue
            l2.append(_l2(e, s, t))
            removable = e.type in ("lamp", "resistor", "rheostat", "motor", "fuse") and s.ok
            if removable:
                alt = _with_states(c, switches, m)
                next(x for x in alt.elements if x.id == e.id).type = "capacitor"   # open in DC
                s2 = solve(alt)
                l3.append(t["remove"].format(i=say(s2.source_current if s2.ok else 0.0, "А")))
            else:
                l3.append("")
        if e.type == "switch" and e.id in switches:
            sw_index.append(len(hs))
        lit = [1 if (e.type == "lamp" and sols[m].ok and abs(sols[m].results.get(e.id).current or 0) > 1e-6) else 0
               for m in range(n_states)] if e.type == "lamp" else []
        hs.append([h["x"], h["y"], h["r"], h.get("lx"), h.get("ly"), l1, l2, l3, lit])
    toggles = []
    for m in range(n_states):
        row = []
        for b, sid in enumerate(switches):
            m2 = m ^ (1 << b)
            row.append(_diff(c, sols[m], sols[m2], by_id[sid].key, bool(m2 >> b & 1), t))
        toggles.append(row)
    ox, oy = plate_offset(layout)
    return {"v": 1, "k": "c", "l": lang, "t": c.title, "mat": [MAT_W, MAT_H], "mk": marker_layout(),
            "off": [round(ox, 1), round(oy, 1)], "pw": round(layout.width, 1), "ph": round(layout.height, 1),
            "hs": hs, "sw": sw_index, "st": init, "tg": toggles}


def graph_payload(res, lang: str = "ru", title: str = "") -> dict:
    """res: graphs.GraphResult (needs res.geom and res.samples)."""
    t = TX[lang]
    g = res.geom
    ox, oy = plate_offset(res.layout)
    a = res.analysis
    return {"v": 1, "k": "g", "l": lang, "t": title, "mat": [MAT_W, MAT_H], "mk": marker_layout(),
            "off": [round(ox, 1), round(oy, 1)], "pw": round(res.layout.width, 1), "ph": round(res.layout.height, 1),
            "gx": [round(g["left"], 2), round(g["top"], 2), round(g["unit"], 4), g["x0"], g["x1"], g["y0"], g["y1"],
                   g["ax_x"], g["ax_y"]],
            "cv": res.samples, "zs": [round(z, 3) for z in a.zeros[:8]],
            "mn": [[round(x, 3), round(y, 3)] for x, y in a.minima[:4]],
            "mx": [[round(x, 3), round(y, 3)] for x, y in a.maxima[:4]],
            "tx": {k: v for k, v in t.items() if k.startswith("g_")}}


def pack(payload: dict) -> str:
    return _pack(payload)


def touch_url(base: str, payload: dict) -> str:
    return f"{base.rstrip('/')}/app/static/touch.html#d={pack(payload)}"


# ------------------------------------------------------------------ printable mat
def _marker_cells(mid: int) -> list[str]:
    return _MARKERS["markers"][str(mid)]


def mat_svg(layout: Layout | None, spec: Spec | None = None, include_sheet: bool = False, qr_matrix=None) -> str:
    """A4 mat with markers and the plate outline. include_sheet=True also prints the tactile drawing inside
    the outline (for swell paper: the sheet and the markers on one page)."""
    spec = spec or Spec()
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{MAT_W}mm" height="{MAT_H}mm" viewBox="0 0 {MAT_W} {MAT_H}">',
           f'<rect width="{MAT_W}" height="{MAT_H}" fill="white"/>']
    for mid, cx, cy, side in marker_layout():
        cell = side / 6
        x0, y0 = cx - side / 2, cy - side / 2
        out.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{side:.2f}" height="{side:.2f}" fill="black"/>')
        for r, row in enumerate(_marker_cells(mid)):
            for col, bit in enumerate(row):
                if bit == "1":
                    out.append(f'<rect x="{x0 + (col + 1) * cell:.2f}" y="{y0 + (r + 1) * cell:.2f}" '
                               f'width="{cell:.2f}" height="{cell:.2f}" fill="white"/>')
    if layout is not None:
        ox, oy = plate_offset(layout)
        k = layout.corner
        W, H = layout.width, layout.height
        pts = [(ox + k, oy), (ox + W, oy), (ox + W, oy + H), (ox, oy + H), (ox, oy + k)]
        d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
        if include_sheet:
            inner = to_svg(layout, spec).split("\n")
            body = [ln for ln in inner if not ln.startswith("<svg") and ln != "</svg>" and 'fill="white"' not in ln]
            out.append(f'<g transform="translate({ox:.2f},{oy:.2f})">' + "".join(body) + "</g>")
        else:
            out.append(f'<path d="{d}" fill="none" stroke="#7a7f87" stroke-width="0.5" stroke-dasharray="3,2"/>')
    if qr_matrix is not None:
        n = len(qr_matrix)
        size = 28.0
        px = size / n
        qx, qy = MARGIN + 1, MAT_H / 2 - size / 2
        for r, row in enumerate(qr_matrix):
            for col, on in enumerate(row):
                if on:
                    out.append(f'<rect x="{qx + col * px:.3f}" y="{qy + r * px:.3f}" width="{px + 0.01:.3f}" '
                               f'height="{px + 0.01:.3f}" fill="black"/>')
    out.append("</svg>")
    return "\n".join(out)


def mat_pdf(layout: Layout, title: str, url: str, lang: str = "ru") -> bytes:
    """Printable A4 mat: markers, plate outline, QR for the teacher's phone, short instructions."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MPoly, Rectangle

    fig = plt.figure(figsize=(MAT_W / 25.4, MAT_H / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, MAT_W)
    ax.set_ylim(MAT_H, 0)
    ax.axis("off")
    for mid, cx, cy, side in marker_layout():
        cell = side / 6
        x0, y0 = cx - side / 2, cy - side / 2
        ax.add_patch(Rectangle((x0, y0), side, side, fc="black", ec="none"))
        for r, row in enumerate(_marker_cells(mid)):
            for col, bit in enumerate(row):
                if bit == "1":
                    ax.add_patch(Rectangle((x0 + (col + 1) * cell, y0 + (r + 1) * cell), cell, cell, fc="white", ec="none"))
    ox, oy = plate_offset(layout)
    k, W, H = layout.corner, layout.width, layout.height
    ax.add_patch(MPoly([(ox + k, oy), (ox + W, oy), (ox + W, oy + H), (ox, oy + H), (ox, oy + k)], closed=True,
                       fill=False, ec="#7a7f87", lw=0.8, ls=(0, (4, 3))))
    import qrcode
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=1)
    q.add_data(url)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    size = max(26.0, min(48.0, ox - MARGIN - 4))     # as big as the free strip left of the plate allows
    px = size / n
    qx, qy = MARGIN, MAT_H / 2 - size / 2
    for r, row in enumerate(m):
        for col, on in enumerate(row):
            if on:
                ax.add_patch(Rectangle((qx + col * px, qy + r * px), px * 1.02, px * 1.02, fc="black", ec="none"))
    hint = {"ru": ("Живой лист: положите пластину в рамку срезанным углом влево вверх.",
                   "Наклейте яркую наклейку на ноготь, телефон держите над листом так, чтобы были видны 4 метки."),
            "kk": ("Тірі парақ: пластинаны рамкаға кесілген бұрышын сол жақ жоғарыға қаратып қойыңыз.",
                   "Тырнаққа ашық түсті жапсырма жабыстырыңыз, телефонды 4 белгі көрінетіндей ұстаңыз.")}[lang]
    ax.text(MAT_W / 2, MARGIN + 3, hint[0], ha="center", va="top", fontsize=7.5, color="#3b4148")
    ax.text(MAT_W / 2, MAT_H - MARGIN - 1, hint[1], ha="center", va="bottom", fontsize=7.5, color="#3b4148")
    ax.text(qx + size / 2, qy + size + 3, "QR", ha="center", va="top", fontsize=6.5, color="#3b4148")
    if title:
        ax.text(MAT_W / 2, MARGIN + 7.5, title, ha="center", va="top", fontsize=8, color="#14181d", weight="bold")
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    return buf.getvalue()
