"""Accessible lesson built from the circuit graph: overview, finger tour, physics, quiz.

Everything is derived deterministically from the parsed circuit and the solver,
so the narration always matches the printed sheet. Kazakh wording should be
reviewed by a teacher.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .components import NAMES
from .model import Circuit
from .solver import Solution, fmt, solve

T = {
    "ru": {
        "dir": {"r": "вправо", "l": "влево", "d": "вниз", "u": "вверх"},
        "then": "затем",
        "intro": "Это электрическая схема{title}. Срезанный угол листа — левый верхний. "
                 "На схеме {n} элементов, их номера написаны шрифтом Брайля, названия — на листе обозначений.",
        "start_src": "Найди источник тока, номер {k}. Начнём от его длинной пластины — это плюс.",
        "start_any": "Начни с левого верхнего угла схемы.",
        "move": "Веди палец {dirs}",
        "reach": "дойдёшь до номера {k}: {name}{val}.",
        "junction": "Здесь развилка: путь делится на {m}.",
        "back": "Вернись к развилке рядом с номером {k} и иди по другому пути.",
        "closed": "Ты вернулся к началу — цепь замкнута.",
        "end": "Это конец пути.",
        "series": "Все элементы соединены последовательно: у тока один путь.",
        "branched": "Цепь разветвлённая: есть параллельные участки, у тока несколько путей.",
        "solved": "Источник даёт {e}. Общее сопротивление {r}, ток от источника {i}.",
        "el_line": "Номер {k}, {name}: напряжение {u}, ток {i}.",
        "voltmeter": "Вольтметр номер {k} покажет {u}.",
        "ammeter": "Амперметр номер {k} покажет {i}.",
        "open_sw": "Ключ номер {k} разомкнут — по этой ветви ток не идёт.",
        "missing": "Чтобы рассчитать токи, укажите значения у элементов: {items}.",
        "short": "Внимание: короткое замыкание! Выводы источника соединены проводом напрямую.",
        "q_amm": "Что покажет амперметр номер {k}?",
        "q_volt": "Что покажет вольтметр номер {k}?",
        "q_switch": "Что произойдёт с током от источника, если разомкнуть ключ номер {k}?",
        "a_switch_zero": "Ток станет равен нулю: цепь разорвётся.",
        "a_switch_val": "Ток изменится с {i0} до {i1}.",
        "q_power": "Какой элемент потребляет наибольшую мощность?",
        "a_power": "Номер {k}, {name}: {p}.",
        "q_junc": "Сколько развилок на схеме?",
        "a_junc": "{n}.",
    },
    "kk": {
        "dir": {"r": "оңға", "l": "солға", "d": "төмен", "u": "жоғары"},
        "then": "содан кейін",
        "intro": "Бұл электр тізбегінің сұлбасы{title}. Парақтың кесілген бұрышы — сол жақ жоғарғы бұрыш. "
                 "Сұлбада {n} элемент бар, олардың нөмірлері Брайль қарпімен жазылған, атаулары — шартты белгілер парағында.",
        "start_src": "Ток көзін тап, нөмірі {k}. Ұзын пластинасынан бастаймыз — бұл плюс.",
        "start_any": "Сұлбаның сол жақ жоғарғы бұрышынан баста.",
        "move": "Саусағыңды {dirs} жүргіз",
        "reach": "{k} нөміріне жетесің: {name}{val}.",
        "junction": "Мұнда тармақталу нүктесі: жол {m} бағытқа бөлінеді.",
        "back": "{k} нөмірінің жанындағы тармақталу нүктесіне қайт та, басқа жолмен жүр.",
        "closed": "Бастапқы нүктеге қайттың — тізбек тұйық.",
        "end": "Жолдың соңы.",
        "series": "Барлық элементтер тізбектей жалғанған: токтың бір ғана жолы бар.",
        "branched": "Тізбек тармақталған: параллель бөліктер бар, токтың бірнеше жолы бар.",
        "solved": "Ток көзі {e} береді. Жалпы кедергі {r}, ток көзінен шығатын ток {i}.",
        "el_line": "{k} нөмір, {name}: кернеу {u}, ток {i}.",
        "voltmeter": "{k} нөмірлі вольтметр {u} көрсетеді.",
        "ammeter": "{k} нөмірлі амперметр {i} көрсетеді.",
        "open_sw": "{k} нөмірлі кілт ажыратулы — бұл тармақпен ток жүрмейді.",
        "missing": "Токты есептеу үшін элементтердің мәндерін көрсетіңіз: {items}.",
        "short": "Назар аударыңыз: қысқа тұйықталу! Ток көзінің шықпалары сыммен тікелей жалғанған.",
        "q_amm": "{k} нөмірлі амперметр нені көрсетеді?",
        "q_volt": "{k} нөмірлі вольтметр нені көрсетеді?",
        "q_switch": "{k} нөмірлі кілтті ажыратса, ток көзінен шығатын ток қалай өзгереді?",
        "a_switch_zero": "Ток нөлге тең болады: тізбек үзіледі.",
        "a_switch_val": "Ток {i0}-ден {i1}-ге дейін өзгереді.",
        "q_power": "Қай элемент ең көп қуат тұтынады?",
        "a_power": "{k} нөмір, {name}: {p}.",
        "q_junc": "Сұлбада неше тармақталу нүктесі бар?",
        "a_junc": "{n}.",
    },
}


@dataclass
class Lesson:
    intro: str
    tour: list[str]
    physics: list[str]
    quiz: list[tuple[str, str]] = field(default_factory=list)

    def script(self) -> list[str]:
        """Ordered phrases for the audio guide."""
        return [self.intro, *self.tour, *self.physics]


def _dir(c: Circuit, a: str, b: str) -> str:
    na, nb = c.nodes[a], c.nodes[b]
    if nb.x > na.x:
        return "r"
    if nb.x < na.x:
        return "l"
    return "d" if nb.y > na.y else "u"


def _join_dirs(dirs: list[str], t: dict) -> str:
    out: list[str] = []
    for d in dirs:
        if not out or out[-1] != d:
            out.append(d)
    return f", {t['then']} ".join(t["dir"][d] for d in out)


def _nearest_key(c: Circuit, node: str) -> int | None:
    n0 = c.nodes[node]
    best = None
    for e in c.elements:
        if not e.key:
            continue
        for nid in (e.a, e.b):
            n = c.nodes[nid]
            d = abs(n.x - n0.x) + abs(n.y - n0.y)
            if best is None or d < best[0]:
                best = (d, e.key)
    return best[1] if best else None


def tour(c: Circuit, lang: str) -> list[str]:
    t = T[lang]
    adj: dict[str, list] = {n: [] for n in c.nodes}
    for e in c.elements:
        adj[e.a].append((e, e.b))
        adj[e.b].append((e, e.a))
    src = next((e for e in c.elements if e.type in ("cell", "battery")), None)
    steps: list[str] = []
    if src:
        start = src.a
        steps.append(t["start_src"].format(k=src.key))
    else:
        start = min(c.nodes, key=lambda n: (c.nodes[n].y, c.nodes[n].x))
        steps.append(t["start_any"])

    used: set[str] = set()
    if src:
        used.add(src.id)  # we stand on the + plate; walk away from the source first
    cur, last_dir, dirs = start, None, []
    stack: list[str] = []
    announced: set[str] = set()
    reached_minus = False

    def unvisited(n):
        return [(e, o) for e, o in adj[n] if e.id not in used]

    while True:
        options = unvisited(cur)
        if c.degree(cur) >= 3 and cur not in announced and len(options) >= 2:
            announced.add(cur)
            if dirs:
                steps.append(t["move"].format(dirs=_join_dirs(dirs, t)) + ".")
                dirs = []
            steps.append(t["junction"].format(m=c.degree(cur) - 1))
        if not options:
            if dirs:
                steps.append(t["move"].format(dirs=_join_dirs(dirs, t)) + ".")
                dirs = []
            while stack and not unvisited(stack[-1]):
                stack.pop()
            if not stack:
                break
            cur = stack[-1]
            k = _nearest_key(c, cur)
            steps.append(t["back"].format(k=k if k else "?"))
            last_dir = None
            continue
        options.sort(key=lambda eo: (0 if _dir(c, cur, eo[1]) == last_dir else 1, eo[0].type == "wire"))
        e, nxt = options[0]
        if len(options) > 1:
            stack.append(cur)
        used.add(e.id)
        d = _dir(c, cur, nxt)
        dirs.append(d)
        if e.type != "wire":
            val = f", {e.value}" if e.value else ""
            steps.append(t["move"].format(dirs=_join_dirs(dirs, t)) + " — "
                         + t["reach"].format(k=e.key, name=NAMES[e.type][lang], val=val))
            dirs = []
        cur, last_dir = nxt, d
        if src and cur == src.b:
            reached_minus = True
    if reached_minus:
        steps.append(t["closed"])
    else:
        steps.append(t["end"])
    return steps


def build_lesson(c: Circuit, lang: str = "ru", sol: Solution | None = None) -> Lesson:
    t = T[lang]
    sol = sol or solve(c)
    keyed = [e for e in c.elements if e.key]
    title = f" «{c.title}»" if c.title else ""
    intro = t["intro"].format(title=title, n=len(keyed))

    # cycle rank on the graph with conductors merged tells series vs branched
    nodes = set(c.nodes)
    rank = len(c.elements) - len(nodes) + 1
    junctions = [n for n in c.nodes if c.degree(n) >= 3]
    physics = [t["series"] if rank <= 1 and not junctions else t["branched"]]

    for e in c.elements:
        if e.type == "switch" and e.state == "open":
            physics.append(t["open_sw"].format(k=e.key))
    if sol.short_circuit:
        physics.append(t["short"])
    elif not sol.ok:
        names = ", ".join(f"№{e.key} {NAMES[e.type][lang]}" for e in c.elements if e.id in sol.missing and e.key)
        physics.append(t["missing"].format(items=names or "—"))
    else:
        src = next(e for e in c.elements if e.type in ("cell", "battery"))
        physics.append(t["solved"].format(e=fmt(sol.results[src.id].voltage, "В"),
                                          r=fmt(sol.total_resistance, "Ом"), i=fmt(abs(sol.source_current or 0), "А")))
        for e in sorted(keyed, key=lambda e: e.key):
            r = sol.results.get(e.id)
            if not r:
                continue
            if e.type == "voltmeter":
                physics.append(t["voltmeter"].format(k=e.key, u=fmt(abs(r.voltage), "В")))
            elif e.type == "ammeter":
                physics.append(t["ammeter"].format(k=e.key, i=fmt(abs(r.current), "А")))
            elif e.type not in ("cell", "battery", "switch"):
                physics.append(t["el_line"].format(k=e.key, name=NAMES[e.type][lang],
                                                   u=fmt(abs(r.voltage), "В"), i=fmt(abs(r.current), "А")))

    return Lesson(intro, tour(c, lang), physics, quiz(c, lang, sol, len(junctions)))


def quiz(c: Circuit, lang: str, sol: Solution, n_junctions: int) -> list[tuple[str, str]]:
    t = T[lang]
    qs: list[tuple[str, str]] = []
    if sol.ok:
        for e in c.elements:
            r = sol.results.get(e.id)
            if e.type == "ammeter" and r:
                qs.append((t["q_amm"].format(k=e.key), fmt(abs(r.current), "А")))
            if e.type == "voltmeter" and r:
                qs.append((t["q_volt"].format(k=e.key), fmt(abs(r.voltage), "В")))
        for e in c.elements:
            if e.type == "switch" and e.state == "closed":
                alt = copy.deepcopy(c)
                next(x for x in alt.elements if x.id == e.id).state = "open"
                s2 = solve(alt)
                i0, i1 = abs(sol.source_current or 0), abs(s2.source_current or 0) if s2.ok else 0.0
                ans = t["a_switch_zero"] if i1 < 1e-9 else t["a_switch_val"].format(i0=fmt(i0, "А"), i1=fmt(i1, "А"))
                qs.append((t["q_switch"].format(k=e.key), ans))
                break
        loads = [(sol.results[e.id].power or 0, e) for e in c.elements
                 if e.key and e.id in sol.results and e.type not in ("cell", "battery", "ammeter", "voltmeter", "switch")]
        if len(loads) >= 2:
            p, e = max(loads, key=lambda pe: abs(pe[0]))
            qs.append((t["q_power"], t["a_power"].format(k=e.key, name=NAMES[e.type][lang], p=fmt(abs(p), "Вт"))))
    qs.append((t["q_junc"], t["a_junc"].format(n=n_junctions)))
    return qs
