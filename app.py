"""TouchSTEM — школьная схема или график становятся листом, который читают пальцами.

Запуск:  streamlit run app.py
Secrets: GEMINI_API_KEY (обязательно для распознавания фото), APP_URL (адрес приложения для QR)
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from touchstem.ai import DEFAULT_MODEL, AIError, parse_circuit_image, parse_graph_image
from touchstem.braille import translate
from touchstem.components import NAMES, TYPES
from touchstem.graphs import FormulaError, build_graph, graph_lesson
from touchstem.guide import guide_html
from touchstem.lesson import build_lesson
from touchstem.model import Circuit, CircuitError
from touchstem.quality import check_layout, print_estimate
from touchstem.render import Layout, Spec, build_diagram, build_legend, stl_with_volume, to_png, to_svg
from touchstem.share import decode, encode_circuit, encode_graph, guide_url, qr_png
from touchstem.solver import solve
from touchstem.teacher import teacher_pdf

ROOT = Path(__file__).parent
EXAMPLES = {"Последовательная цепь": "series.json", "Параллельные лампы": "parallel.json"}
GRAPH_EXAMPLES = {
    "Парабола": ("x^2 - 4", -4.0, 4.0, -5.0, 6.0),
    "Прямая": ("2x + 1", -3.0, 3.0, -5.0, 7.0),
    "Синусоида": ("sin(x)", -6.3, 6.3, -2.0, 2.0),
    "Гипербола": ("1/x", -5.0, 5.0, -5.0, 5.0),
}

st.set_page_config(page_title="TouchSTEM — схемы и графики для незрячих учеников", page_icon="⠿",
                   layout="wide", initial_sidebar_state="collapsed")


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, os.environ.get(name, default)))
    except Exception:
        return os.environ.get(name, default)


APP_URL = secret("APP_URL", "https://touchstem.streamlit.app")

# ------------------------------------------------------------------ style
st.markdown("""
<style>
.block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1260px; }
header[data-testid="stHeader"] { background: transparent; }
h1, h2, h3 { letter-spacing: -0.01em; }
h3 { font-size: 1.05rem !important; margin-top: .2rem !important; }

.ts-head { display: grid; grid-template-columns: auto 1fr; gap: 10px 40px; align-items: end;
           padding: 6px 0 22px; border-bottom: 1px solid #D9DCD3; margin-bottom: 20px; }
.ts-word { font-family: "Unbounded", sans-serif; font-weight: 700; font-size: clamp(36px, 5.2vw, 60px);
           letter-spacing: -0.03em; line-height: .95; color: #14181D; }
.ts-braille { display: flex; gap: 11px; margin-top: 14px; }
.ts-cell { display: grid; grid-template-columns: repeat(2, 10px); grid-template-rows: repeat(3, 10px);
           grid-auto-flow: column; gap: 4px; }
.ts-dot { width: 10px; height: 10px; border-radius: 50%; box-shadow: inset 0 0 0 1px #E2E4DD; }
.ts-dot.on { box-shadow: 1px 1.6px 1.4px rgba(58, 64, 56, .5);
             background: radial-gradient(circle at 34% 30%, #ffffff 0 16%, #e2e4dd 46%, #b5b9b0 100%); }
.ts-lede { font-size: 1.12rem; line-height: 1.5; max-width: 58ch; margin: 0 0 12px; color: #2a3038; }
.ts-key { display: flex; gap: 22px; flex-wrap: wrap; font-size: .9rem; color: #4a525c; }
.ts-key span::before { content: ""; display: inline-block; width: 12px; height: 12px; border-radius: 3px;
                       margin-right: 7px; vertical-align: -1px; }
.ts-key .raised::before { background: #000; }
.ts-key .teacher::before { background: #2440C8; }
@media (max-width: 760px) { .ts-head { grid-template-columns: 1fr; } }

.ts-score { display: flex; align-items: baseline; gap: 12px; margin: 2px 0 6px; }
.ts-score b { font-family: "Unbounded", sans-serif; font-size: 2rem; font-weight: 600; }
.ts-score span { color: #4a525c; }
.ts-checks { list-style: none; padding: 0; margin: 8px 0 0; }
.ts-checks li { display: grid; grid-template-columns: 26px 1fr; gap: 8px; padding: 10px 0; border-top: 1px solid #E6E8E1; }
.ts-checks li i { font-style: normal; font-weight: 700; width: 22px; height: 22px; border-radius: 50%;
                  display: inline-grid; place-items: center; font-size: 13px; color: #fff; }
.ts-checks .ok i { background: #1E7F4F; } .ts-checks .warn i { background: #B7791F; } .ts-checks .fail i { background: #B42318; }
.ts-checks small { display: block; color: #4a525c; margin-top: 2px; }
.ts-steps { padding-left: 1.3rem; } .ts-steps li { margin: .35rem 0; line-height: 1.5; }
.ts-meta { color: #4a525c; font-size: .92rem; }
.ts-braille-line { font-size: 1.5rem; letter-spacing: .08em; line-height: 1.6; color: #14181D; }
</style>
""", unsafe_allow_html=True)


def braille_wordmark(word: str) -> str:
    latin = {"t": "2345", "o": "135", "u": "136", "c": "14", "h": "125", "s": "234", "e": "15", "m": "134"}
    cells = []
    for ch in word.lower():
        dots = latin.get(ch, "")
        cells.append('<span class="ts-cell" aria-hidden="true">' +
                     "".join(f'<span class="ts-dot{" on" if str(d) in dots else ""}"></span>' for d in range(1, 7)) +
                     "</span>")
    return "".join(cells)


def header():
    st.markdown(f"""
<div class="ts-head">
  <div><div class="ts-word">TouchSTEM</div><div class="ts-braille" title="TouchSTEM шрифтом Брайля">{braille_wordmark("touchstem")}</div></div>
  <div>
    <p class="ts-lede">Сфотографируйте схему из учебника или введите формулу графика. Через пару минут у вас будет
    лист для 3D-печати или рельефной бумаги, подписи шрифтом Брайля, урок и аудиогид для ученика.</p>
    <div class="ts-key"><span class="raised">чёрное — будет рельефным</span><span class="teacher">синее — подсказки для учителя, не печатается</span></div>
  </div>
</div>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ cached builders
def spec_from(d: dict) -> Spec:
    return Spec(**d)


@st.cache_data(show_spinner=False, max_entries=48)
def circuit_bundle(cjson: str, lang: str, spec_d: dict, price: float, app_url: str) -> dict:
    spec = spec_from(spec_d)
    c = Circuit.from_dict(json.loads(cjson))
    diagram = build_diagram(c, spec, lang)
    legend, legend_uni = build_legend(c, lang, spec)
    sol = solve(c)
    lesson = build_lesson(c, lang, sol)
    n_sym = sum(1 for e in c.elements if e.key)
    report = check_layout(diagram, spec, n_sym, c.warnings + legend.warnings, lang)
    stl, vol = stl_with_volume(diagram, spec)
    stl_leg, vol_leg = stl_with_volume(legend, spec)
    est = print_estimate(vol + vol_leg, price)
    url = guide_url(app_url, encode_circuit(c, lang))
    qr = qr_png(url)
    legend_lines = [t for _, t in [(0, "")] + [(k, f"{k} — {txt}") for k, txt in c.legend(lang)]]
    pdf = teacher_pdf(c.title, to_png(diagram, spec, style="plan"), legend_lines, lesson, report, est, qr, lang)
    return {"diagram": diagram, "legend": legend, "legend_uni": legend_uni, "lesson": lesson, "report": report,
            "stl": stl, "stl_leg": stl_leg, "est": est, "url": url, "qr": qr, "pdf": pdf, "n": n_sym,
            "svg": to_svg(diagram, spec), "svg_leg": to_svg(legend, spec), "svg_teacher": to_svg(diagram, spec, ink=True),
            "sol_ok": sol.ok, "title": c.title, "warnings": c.warnings}


@st.cache_data(show_spinner=False, max_entries=48)
def graph_bundle(formula: str, rng: tuple, title: str, lang: str, spec_d: dict, price: float, app_url: str) -> dict:
    spec = spec_from(spec_d)
    x0, x1, y0, y1 = rng
    res = build_graph(formula, (x0, x1), (y0, y1), lang, spec)
    lesson = graph_lesson(formula, (x0, x1), (y0, y1), res, lang, title)
    legend = _legend_from_lines(res.legend_lines, lang, spec)
    legend_uni = "\n".join(translate(t, lang).unicode for t in res.legend_lines)
    report = check_layout(res.layout, spec, 4, [], lang)
    stl, vol = stl_with_volume(res.layout, spec)
    stl_leg, vol_leg = stl_with_volume(legend, spec)
    est = print_estimate(vol + vol_leg, price)
    url = guide_url(app_url, encode_graph(formula, rng, lang, title))
    qr = qr_png(url)
    pdf = teacher_pdf(title or f"y = {formula}", to_png(res.layout, spec, style="plan"), [""] + res.legend_lines,
                      lesson, report, est, qr, lang)
    return {"diagram": res.layout, "legend": legend, "legend_uni": legend_uni, "lesson": lesson, "report": report,
            "stl": stl, "stl_leg": stl_leg, "est": est, "url": url, "qr": qr, "pdf": pdf, "n": 4,
            "svg": to_svg(res.layout, spec), "svg_leg": to_svg(legend, spec),
            "svg_teacher": to_svg(res.layout, spec, ink=True), "title": title or f"y = {formula}", "warnings": []}


def _legend_from_lines(lines: list[str], lang: str, spec: Spec) -> Layout:
    from touchstem.render import cells_size, place_cells
    max_cells = int((spec.max_width - 2 * spec.margin) // spec.cell_pitch)
    rows = []
    for text in lines:
        cells = translate(text, lang).cells
        while len(cells) > max_cells:
            cut = max((i for i, c in enumerate(cells[:max_cells + 1]) if c == "0"), default=max_cells)
            rows.append(cells[:cut])
            cells = cells[cut + 1:]
        rows.append(cells)
    longest = max((len(r) for r in rows), default=1)
    W = max(cells_size(longest, spec)[0] + 2 * spec.margin, 80)
    H = len(rows) * spec.line_pitch + 2 * spec.margin
    dots = []
    for i, r in enumerate(rows):
        dots += place_cells(r, spec.margin, spec.margin + i * spec.line_pitch, spec)
    from shapely.geometry import Polygon
    return Layout(W, H, Polygon(), dots, [])


@st.cache_data(show_spinner=False, max_entries=96)
def preview(kind: str, key: str, style: str, ink: bool, _layout: Layout, spec_d: dict) -> bytes:
    return to_png(_layout, spec_from(spec_d), style=style, show_ink=ink)


@st.cache_data(show_spinner=False)
def sample_sheet(lang: str, spec_d: dict) -> bytes:
    c = Circuit.from_dict(json.loads((ROOT / "examples" / "parallel.json").read_text(encoding="utf-8")))
    return to_png(build_diagram(c, spec_from(spec_d), lang), spec_from(spec_d), style="relief", show_ink=False)


# ------------------------------------------------------------------ audio-guide route (student's phone)
def render_guide(param: str):
    try:
        d = decode(param)
    except Exception:
        st.error("Ссылка повреждена. Попросите учителя распечатать QR-код заново.")
        st.stop()
    lang = d["lang"]
    spec_d = asdict(Spec())
    if d["kind"] == "graph":
        x0, x1, y0, y1 = d["range"]
        res = build_graph(d["formula"], (x0, x1), (y0, y1), lang)
        lesson = graph_lesson(d["formula"], (x0, x1), (y0, y1), res, lang, d.get("title", ""))
        title = d.get("title") or ("Функция графигі" if lang == "kk" else "График функции")
    else:
        c = Circuit.from_dict(d["circuit"])
        lesson = build_lesson(c, lang)
        title = c.title or ("Электр тізбегі" if lang == "kk" else "Электрическая схема")
    st.markdown(f'<div class="ts-word" style="font-size:22px;margin-bottom:6px">TouchSTEM</div>'
                f'<h2 style="margin:0 0 8px">{html.escape(title)}</h2>', unsafe_allow_html=True)
    steps = lesson.script() + [f"{q} — {a}" for q, a in lesson.quiz]
    components.html(guide_html(steps, lang, title), height=640, scrolling=False)
    _ = spec_d


qp = st.query_params
if "g" in qp:
    render_guide(qp["g"])
    st.stop()

# ------------------------------------------------------------------ settings
with st.sidebar:
    st.markdown("### Настройки")
    lang = st.radio("Язык подписей и урока", ["ru", "kk"], horizontal=True,
                    format_func=lambda x: {"ru": "Русский", "kk": "Қазақша"}[x])
    with st.expander("Размеры листа, мм"):
        grid = st.slider("Шаг сетки схемы", 26, 50, 36)
        max_w = st.slider("Макс. ширина", 120, 280, 200)
        max_h = st.slider("Макс. высота", 100, 280, 180)
        plate_t = st.slider("Толщина основы (3D)", 1.0, 3.0, 1.6, 0.2)
        line_h = st.slider("Высота рельефа (3D)", 0.5, 1.5, 0.9, 0.1)
    price = st.number_input("Цена пластика, ₸ за кг", 3000, 30000, 9000, 500)
    api_key = secret("GEMINI_API_KEY")
    if not api_key:
        api_key = st.text_input("Gemini API key", type="password", help="Нужен только для распознавания фото")
    model = secret("GEMINI_MODEL", DEFAULT_MODEL)
    st.caption("Брайль: таблицы liblouis (русский и казахский, без сокращений). "
               "Проверьте подписи с тифлопедагогом перед уроком.")

spec_d = asdict(Spec(grid=float(grid), max_width=float(max_w), max_height=float(max_h),
                     plate_t=float(plate_t), line_h=float(line_h)))

for k, v in {"circuit_json": None, "t0": None, "done_at": None,
             "graph": {"formula": "x^2 - 4", "x0": -4.0, "x1": 4.0, "y0": -5.0, "y1": 6.0, "title": ""}}.items():
    st.session_state.setdefault(k, v)

header()
mode = st.segmented_control("Что превращаем в тактильный лист", ["Электрическая схема", "График функции"],
                            default="Электрическая схема", label_visibility="collapsed") or "Электрическая схема"


def start_timer():
    st.session_state.t0 = time.time()
    st.session_state.done_at = None


def mark_done():
    if st.session_state.t0 and not st.session_state.done_at:
        st.session_state.done_at = time.time()


# ------------------------------------------------------------------ circuit input
bundle = None
if mode == "Электрическая схема":
    left, right = st.columns([5, 7], gap="large")
    with left:
        st.markdown("### 1. Схема из учебника")
        photo = st.file_uploader("Фото или скан схемы", type=["png", "jpg", "jpeg", "webp"],
                                 label_visibility="collapsed")
        if photo is not None:
            st.image(photo, width=320)
            if st.button("Распознать схему", type="primary", width="stretch"):
                start_timer()
                with st.spinner("Читаю схему…"):
                    try:
                        st.session_state.circuit_json = parse_circuit_image(
                            photo.getvalue(), photo.type or "image/jpeg", api_key, model)
                    except AIError as exc:
                        st.error(f"{exc}. Проверьте ключ в настройках или выберите пример ниже.")
        pick = st.pills("Или откройте пример", list(EXAMPLES), selection_mode="single", key="ex_pick")
        if pick and st.session_state.get("ex_loaded") != pick:
            st.session_state.circuit_json = json.loads((ROOT / "examples" / EXAMPLES[pick]).read_text(encoding="utf-8"))
            st.session_state.ex_loaded = pick
            start_timer()

        raw = st.session_state.circuit_json
        if raw is not None:
            try:
                circuit = Circuit.from_dict(raw)
            except CircuitError as exc:
                st.error(f"Схему не удалось собрать: {exc}. Исправьте JSON ниже или загрузите другое фото.")
                circuit = None
            if circuit:
                st.markdown("### 2. Проверьте элементы")
                if circuit.notes:
                    st.info(circuit.notes)
                ru_name = {t: NAMES[t]["ru"] for t in TYPES}
                ru_type = {v: k for k, v in ru_name.items()}
                rows = sorted(({"№": e.key, "id": e.id, "тип": ru_name[e.type], "значение": e.value,
                                "ключ": ("замкнут" if e.state == "closed" else "разомкнут") if e.type == "switch" else "—"}
                               for e in circuit.elements if e.type != "wire"), key=lambda r: r["№"])
                edited = st.data_editor(
                    rows, hide_index=True, width="stretch", disabled=["№", "id"], key="editor",
                    column_config={
                        "id": None,
                        "тип": st.column_config.SelectboxColumn(options=[ru_name[t] for t in TYPES if t != "wire"],
                                                                required=True, help="Тип элемента"),
                        "значение": st.column_config.TextColumn(help="Например «4,5 В», «10 Ом», «3,5 В 0,25 А»"),
                        "ключ": st.column_config.SelectboxColumn(options=["—", "замкнут", "разомкнут"]),
                    })
                changed = False
                by_id = {e.id: e for e in circuit.elements}
                for row in edited:
                    e = by_id.get(row["id"])
                    if not e:
                        continue
                    new_state = "open" if row["ключ"] == "разомкнут" else "closed"
                    new_type = ru_type.get(row["тип"], e.type)
                    if e.type != new_type or e.value != (row["значение"] or "") or (e.type == "switch" and e.state != new_state):
                        e.type, e.value, e.state, changed = new_type, row["значение"] or "", new_state, True
                if changed:
                    st.session_state.circuit_json = circuit.to_dict()
                    st.rerun()
                st.caption("Значения нужны для расчёта токов в уроке. Ключ можно разомкнуть — урок пересчитается.")
            with st.expander("JSON схемы"):
                txt = st.text_area("JSON", json.dumps(raw, ensure_ascii=False, indent=1), height=220,
                                   label_visibility="collapsed")
                if st.button("Применить JSON"):
                    try:
                        st.session_state.circuit_json = json.loads(txt)
                        st.rerun()
                    except json.JSONDecodeError as exc:
                        st.error(f"В JSON ошибка: {exc}")
            if circuit:
                with st.spinner("Собираю лист…"):
                    bundle = circuit_bundle(json.dumps(circuit.to_dict(), ensure_ascii=False, sort_keys=True),
                                            lang, spec_d, float(price), APP_URL)
        else:
            st.markdown('<p class="ts-meta">Загрузите фото схемы или откройте пример, чтобы увидеть, как это работает.</p>',
                        unsafe_allow_html=True)
    if bundle is None:
        with right:
            st.markdown("### Так выглядит готовый лист")
            st.image(sample_sheet(lang, spec_d), width="stretch")
            st.markdown('<p class="ts-meta">Параллельное соединение ламп: рельефные линии, номера элементов шрифтом '
                        'Брайля, срезанный угол для ориентации. Откройте пример слева — появятся урок, аудиогид и файлы для печати.</p>',
                        unsafe_allow_html=True)

# ------------------------------------------------------------------ graph input
else:
    left, right = st.columns([5, 7], gap="large")
    g = st.session_state.graph
    with left:
        st.markdown("### 1. Функция")
        gpick = st.pills("Примеры", list(GRAPH_EXAMPLES), selection_mode="single", key="g_pick")
        if gpick and st.session_state.get("g_loaded") != gpick:
            f, a, b, c_, d_ = GRAPH_EXAMPLES[gpick]
            g.update(formula=f, x0=a, x1=b, y0=c_, y1=d_, title="")
            st.session_state.g_loaded = gpick
            start_timer()
        g["formula"] = st.text_input("y =", g["formula"], help="Например: x^2 - 4, 2x + 1, sin(x), sqrt(x), 1/x, |x|")
        c1, c2 = st.columns(2)
        g["x0"] = c1.number_input("x от", value=float(g["x0"]), step=1.0)
        g["x1"] = c2.number_input("x до", value=float(g["x1"]), step=1.0)
        g["y0"] = c1.number_input("y от", value=float(g["y0"]), step=1.0)
        g["y1"] = c2.number_input("y до", value=float(g["y1"]), step=1.0)
        g["title"] = st.text_input("Название листа (необязательно)", g["title"])
        gphoto = st.file_uploader("Или фото графика из учебника", type=["png", "jpg", "jpeg", "webp"], key="gphoto")
        if gphoto is not None and st.button("Распознать график", type="primary"):
            start_timer()
            with st.spinner("Читаю график…"):
                try:
                    r = parse_graph_image(gphoto.getvalue(), gphoto.type or "image/jpeg", api_key, model)
                    g.update(formula=str(r.get("formula", g["formula"])), x0=float(r.get("x_min", g["x0"])),
                             x1=float(r.get("x_max", g["x1"])), y0=float(r.get("y_min", g["y0"])),
                             y1=float(r.get("y_max", g["y1"])), title=str(r.get("title", "") or ""))
                    if r.get("notes"):
                        st.info(r["notes"])
                    st.rerun()
                except (AIError, ValueError, TypeError) as exc:
                    st.error(f"{exc}. Введите формулу вручную.")
        try:
            with st.spinner("Собираю лист…"):
                bundle = graph_bundle(g["formula"], (g["x0"], g["x1"], g["y0"], g["y1"]), g["title"], lang,
                                      spec_d, float(price), APP_URL)
        except FormulaError as exc:
            st.error(str(exc))

# ------------------------------------------------------------------ sheet + tabs
if bundle:
    with right:
        st.markdown("### 3. Тактильный лист" if mode == "Электрическая схема" else "### 2. Тактильный лист")
        v1, v2 = st.columns([3, 2])
        style = v1.segmented_control("Вид", ["Рельеф", "Чертёж"], default="Рельеф",
                                     label_visibility="collapsed") or "Рельеф"
        ink = v2.toggle("Подсказки учителя", value=True)
        key = hashlib.md5(bundle["svg"].encode()).hexdigest()
        img = preview("d", key + lang, "relief" if style == "Рельеф" else "plan", ink, bundle["diagram"], spec_d)
        st.image(img, width="stretch")
        rep = bundle["report"]
        tone = "#1E7F4F" if rep.score >= 85 else "#B7791F" if rep.score >= 65 else "#B42318"
        st.markdown(f'<div class="ts-score"><b style="color:{tone}">{rep.score}</b>'
                    f'<span>из 100 по правилам тактильной графики</span></div>'
                    f'<p class="ts-meta">Размер {bundle["diagram"].width:.0f} на {bundle["diagram"].height:.0f} мм</p>',
                    unsafe_allow_html=True)

    with right:
        t_lesson, t_audio, t_check, t_files = st.tabs(["Урок", "Аудиогид", "Проверка", "Файлы"])
        lesson = bundle["lesson"]
        with t_lesson:
            st.write(lesson.intro)
            st.markdown("### Маршрут пальца")
            st.markdown('<ol class="ts-steps">' + "".join(f"<li>{html.escape(s)}</li>" for s in lesson.tour) + "</ol>",
                        unsafe_allow_html=True)
            st.markdown("### Что важно")
            st.markdown('<ul class="ts-steps">' + "".join(f"<li>{html.escape(s)}</li>" for s in lesson.physics) + "</ul>",
                        unsafe_allow_html=True)
            st.markdown("### Вопросы для самопроверки")
            for q, ans in lesson.quiz:
                with st.expander(q):
                    st.write(ans)
        with t_audio:
            a, b = st.columns([7, 4], gap="large")
            with a:
                steps = lesson.script() + [f"{q} — {ans}" for q, ans in lesson.quiz]
                components.html(guide_html(steps, lang, bundle["title"]), height=560)
            with b:
                st.image(bundle["qr"], width=220)
                st.write("Ученик наводит камеру телефона на QR-код — открывается этот аудиогид. "
                         "QR уже есть на листе учителя (PDF).")
                st.link_button("Открыть как ученик", bundle["url"])
                st.caption("Голос — встроенный в телефон. Если казахского голоса нет, текст читает русский голос, "
                           "а TalkBack или VoiceOver прочитают текст на экране.")
        with t_check:
            rep = bundle["report"]
            icon = {"ok": "✓", "warn": "!", "fail": "×"}
            st.markdown(f'<div class="ts-score"><b>{rep.score}</b><span>из 100</span></div>'
                        '<ul class="ts-checks">' +
                        "".join(f'<li class="{c.status}"><i>{icon[c.status]}</i><div>{html.escape(c.name)}'
                                f'<small>{html.escape(c.detail)}</small></div></li>' for c in rep.checks) + "</ul>",
                        unsafe_allow_html=True)
            st.caption("Проверка следует правилам тактильной графики: расстояние между линиями, отступ Брайля, "
                       "плотность, число символов, размер. Последнее слово — за учеником, который читает лист.")
        with t_files:
            est = bundle["est"]
            name = "".join(ch if ch.isalnum() else "_" for ch in (bundle["title"] or "touchstem"))[:40] or "touchstem"
            cost = f"{est.cost_tenge:,.0f}".replace(",", "\u202f")
            hours = f"{est.minutes / 60:.1f}".replace(".", ",")
            st.markdown(f'<p class="ts-meta">3D-печать двух пластин: около {est.grams:.0f} г пластика, '
                        f'примерно {cost} ₸ и {hours} ч на обычном принтере.</p>', unsafe_allow_html=True)
            d1, d2, d3 = st.columns(3)
            with d1:
                st.markdown("**Для учителя**")
                st.download_button("Лист учителя, PDF", bundle["pdf"], f"{name}_teacher.pdf", "application/pdf",
                                   on_click=mark_done, type="primary", width="stretch")
                st.download_button("Превью, SVG", bundle["svg_teacher"], f"{name}_teacher.svg",
                                   width="stretch")
            with d2:
                st.markdown("**3D-печать**")
                st.download_button("Схема, STL", bundle["stl"], f"{name}.stl", on_click=mark_done, width="stretch")
                st.download_button("Обозначения, STL", bundle["stl_leg"], f"{name}_legend.stl", on_click=mark_done,
                                   width="stretch")
            with d3:
                st.markdown("**Рельефная бумага, 1:1**")
                st.download_button("Схема, SVG", bundle["svg"], f"{name}.svg", on_click=mark_done, width="stretch")
                st.download_button("Обозначения, SVG", bundle["svg_leg"], f"{name}_legend.svg", on_click=mark_done,
                                   width="stretch")
            st.markdown("**Обозначения шрифтом Брайля** — для брайлевского дисплея или принтера")
            st.markdown(f'<div class="ts-braille-line">{html.escape(bundle["legend_uni"]).replace(chr(10), "<br>")}</div>',
                        unsafe_allow_html=True)
            st.download_button("Текст Брайля, TXT", bundle["legend_uni"], f"{name}_braille.txt")
            if st.session_state.done_at and st.session_state.t0:
                st.success(f"От загрузки до файла: {(st.session_state.done_at - st.session_state.t0) / 60:.1f} мин. "
                           "Запишите время для замера.")
