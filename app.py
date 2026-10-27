"""TouchSTEM — фото схемы -> тактильная версия с подписями шрифтом Брайля.

Запуск локально:  streamlit run app.py
Ключ Gemini:      .streamlit/secrets.toml -> GEMINI_API_KEY = "..."  (или переменная окружения)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import streamlit as st

from touchstem.ai import DEFAULT_MODEL, AIError, parse_circuit_image
from touchstem.components import NAMES, TYPES
from touchstem.model import Circuit, CircuitError
from touchstem.render import Spec, build_diagram, build_legend, to_png, to_stl, to_svg

EXAMPLES = Path(__file__).parent / "examples"

st.set_page_config(page_title="TouchSTEM", page_icon="⠿", layout="wide")


def secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, os.environ.get(name, default))
    except Exception:
        return os.environ.get(name, default)


# ---------------- sidebar
with st.sidebar:
    st.header("Настройки")
    lang = st.radio("Язык подписей", ["ru", "kk"], format_func=lambda x: {"ru": "Русский", "kk": "Қазақша"}[x],
                    horizontal=True)
    st.subheader("Размеры, мм")
    grid = st.slider("Шаг сетки", 26, 50, 36)
    max_w = st.slider("Макс. ширина листа", 120, 280, 200)
    plate_t = st.slider("Толщина основы (3D)", 1.0, 3.0, 2.0, 0.2)
    line_h = st.slider("Высота линий (3D)", 0.5, 1.5, 0.9, 0.1)
    api_key = secret("GEMINI_API_KEY") or st.text_input("Gemini API key", type="password")
    model = secret("GEMINI_MODEL", DEFAULT_MODEL)
    st.caption("Шрифт Брайля: таблицы liblouis (ru-litbrl, kk). Подписи — без заглавных; "
               "проверьте с тифлопедагогом перед уроком.")

spec = Spec(grid=float(grid), max_width=float(max_w), plate_t=float(plate_t), line_h=float(line_h))

st.title("TouchSTEM ⠿")
st.write("Сфотографируйте электрическую схему из учебника — получите тактильную версию "
         "для 3D-печати или рельефной бумаги с подписями шрифтом Брайля.")

if "circuit_json" not in st.session_state:
    st.session_state.circuit_json = None
    st.session_state.t0 = None
    st.session_state.done_at = None

# ---------------- step 1: input
col_in, col_ex = st.columns([3, 2])
with col_in:
    photo = st.file_uploader("1. Фото или скан схемы", type=["png", "jpg", "jpeg", "webp"])
    if photo is not None:
        st.image(photo, width=360)
        if st.button("Распознать схему", type="primary"):
            st.session_state.t0 = time.time()
            st.session_state.done_at = None
            with st.spinner("AI читает схему…"):
                try:
                    raw = parse_circuit_image(photo.getvalue(), photo.type or "image/jpeg", api_key, model)
                    st.session_state.circuit_json = raw
                except AIError as exc:
                    st.error(str(exc))
with col_ex:
    st.write("Или откройте пример:")
    for f in sorted(EXAMPLES.glob("*.json")):
        if st.button(f"Пример: {f.stem}"):
            st.session_state.circuit_json = json.loads(f.read_text(encoding="utf-8"))
            st.session_state.t0 = time.time()
            st.session_state.done_at = None

raw = st.session_state.circuit_json
if raw is None:
    st.stop()

# ---------------- step 2: review & edit
st.subheader("2. Проверьте элементы")
try:
    circuit = Circuit.from_dict(raw)
except CircuitError as exc:
    st.error(f"Схема не распознана: {exc}")
    raw_text = st.text_area("JSON схемы (можно исправить вручную)", json.dumps(raw, ensure_ascii=False, indent=1),
                            height=300)
    if st.button("Применить JSON"):
        st.session_state.circuit_json = json.loads(raw_text)
        st.rerun()
    st.stop()

if circuit.notes:
    st.info(f"Комментарий AI: {circuit.notes}")

rows = sorted(({"№": e.key, "id": e.id, "тип": e.type, "значение": e.value, "подпись": e.label}
               for e in circuit.elements if e.type != "wire"), key=lambda r: r["№"])
edited = st.data_editor(
    rows, hide_index=True, width="stretch", disabled=["№", "id"],
    column_config={"тип": st.column_config.SelectboxColumn(options=list(TYPES), required=True)},
    key="editor",
)
changed = False
by_id = {e.id: e for e in circuit.elements}
for row in edited:
    e = by_id.get(row["id"])
    if e and (e.type != row["тип"] or e.value != (row["значение"] or "")):
        e.type, e.value, changed = row["тип"], row["значение"] or "", True
if changed:
    st.session_state.circuit_json = circuit.to_dict()
    st.rerun()

with st.expander("Расширенно: JSON схемы"):
    raw_text = st.text_area("JSON", json.dumps(circuit.to_dict(), ensure_ascii=False, indent=1), height=260)
    if st.button("Применить изменения JSON"):
        try:
            st.session_state.circuit_json = json.loads(raw_text)
            st.rerun()
        except json.JSONDecodeError as exc:
            st.error(f"Ошибка JSON: {exc}")

# ---------------- step 3: tactile output
st.subheader("3. Тактильная версия")
diagram = build_diagram(circuit, spec, lang)
legend, legend_unicode = build_legend(circuit, lang, spec)
for w in circuit.warnings + diagram.warnings + legend.warnings:
    st.warning(w)

c1, c2 = st.columns([3, 2])
with c1:
    st.image(to_png(diagram, spec), caption=f"Схема {diagram.width:.0f}×{diagram.height:.0f} мм "
                                           "(синие цифры — только для учителя, не печатаются)")
with c2:
    st.image(to_png(legend, spec), caption=f"Обозначения {legend.width:.0f}×{legend.height:.0f} мм")
    st.code(legend_unicode, language=None)


def mark_done():
    if st.session_state.t0 and not st.session_state.done_at:
        st.session_state.done_at = time.time()


name = (circuit.title or "scheme").replace(" ", "_")[:40]
st.subheader("4. Скачать")
d1, d2, d3 = st.columns(3)
with d1:
    st.markdown("**3D-печать (STL)**")
    st.download_button("Схема .stl", to_stl(diagram, spec), f"{name}.stl", on_click=mark_done)
    st.download_button("Обозначения .stl", to_stl(legend, spec), f"{name}_legend.stl", on_click=mark_done)
with d2:
    st.markdown("**Рельефная бумага / печать (SVG, 1:1)**")
    st.download_button("Схема .svg", to_svg(diagram, spec), f"{name}.svg", on_click=mark_done)
    st.download_button("Обозначения .svg", to_svg(legend, spec), f"{name}_legend.svg", on_click=mark_done)
with d3:
    st.markdown("**Для учителя**")
    st.download_button("Превью с цифрами .svg", to_svg(diagram, spec, ink=True), f"{name}_teacher.svg")
    st.download_button("Брайль-текст .txt", legend_unicode, f"{name}_legend_braille.txt")
    st.download_button("Схема .json", json.dumps(circuit.to_dict(), ensure_ascii=False, indent=1), f"{name}.json")

if st.session_state.done_at and st.session_state.t0:
    minutes = (st.session_state.done_at - st.session_state.t0) / 60
    st.success(f"Время от загрузки до файла: {minutes:.1f} мин — запишите для замера.")
