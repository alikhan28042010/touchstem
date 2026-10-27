import json
from pathlib import Path

import pytest

from touchstem.graphs import FormulaError, build_graph, compile_formula, graph_lesson
from touchstem.lesson import build_lesson
from touchstem.model import Circuit
from touchstem.quality import check_layout, print_estimate
from touchstem.render import build_diagram, stl_with_volume
from touchstem.share import decode, encode_circuit, encode_graph
from touchstem.solver import fmt, quantities, solve

EX = Path(__file__).parents[1] / "examples"


def load(name):
    return Circuit.from_dict(json.loads((EX / f"{name}.json").read_text(encoding="utf-8")))


def test_series_solution_matches_ohms_law():
    s = solve(load("series"))       # 4,5 В; лампа 3,5 В 0,25 А = 14 Ом; резистор 10 Ом
    assert s.ok
    assert s.total_resistance == pytest.approx(24.0)
    assert abs(s.source_current) == pytest.approx(4.5 / 24)


def test_parallel_lamps_split_current():
    s = solve(load("parallel"))
    assert s.ok and s.total_resistance == pytest.approx(7.0)   # two 14 Ом in parallel


def test_open_switch_stops_current():
    c = load("series")
    next(e for e in c.elements if e.type == "switch").state = "open"
    assert solve(c).source_current == 0.0


def test_short_circuit_detected():
    c = load("series")
    c.elements.append(type(c.elements[0])("short", "wire", c.elements[0].a, c.elements[0].b))
    s = solve(c)
    assert not s.ok and s.short_circuit


def test_quantities_and_format():
    assert quantities("2 кОм") == {"Ом": 2000.0}
    assert quantities("3,5 В 0,25 А") == {"В": 3.5, "А": 0.25}
    assert fmt(0.1875, "А") == "188 мА" and fmt(1500, "Ом") == "1,5 кОм"


@pytest.mark.parametrize("lang", ["ru", "kk"])
def test_lesson_tour_visits_every_component(lang):
    c = load("parallel")
    lesson = build_lesson(c, lang)
    text = " ".join(lesson.tour)
    for e in c.elements:
        if e.key:
            assert str(e.key) in text
    assert lesson.quiz


def test_share_roundtrip():
    c = load("series")
    d = decode(encode_circuit(c, "kk"))
    assert d["kind"] == "circuit" and d["lang"] == "kk"
    assert len(Circuit.from_dict(d["circuit"]).elements) == len(c.elements)
    g = decode(encode_graph("x^2 - 4", (-4, 4, -5, 6), "ru"))
    assert g["formula"] == "x^2 - 4" and g["range"] == [-4, 4, -5, 6]


@pytest.mark.parametrize("bad", ["__import__('os')", "exec(x)", "x + y", "open('f')", "x" * 100])
def test_formula_whitelist_blocks_code(bad):
    with pytest.raises(FormulaError):
        compile_formula(bad)


def test_parabola_analysis():
    r = build_graph("x^2 - 4", (-4, 4), (-5, 6))
    assert r.analysis.zeros == [-2.0, 2.0]
    assert r.analysis.minima and r.analysis.minima[0][1] == pytest.approx(-4, abs=1e-3)
    lesson = graph_lesson("x^2 - 4", (-4, 4), (-5, 6), r)
    assert any("-4" in s for s in lesson.tour)


def test_readability_and_print_estimate():
    c = load("parallel")
    lay = build_diagram(c)
    rep = check_layout(lay, n_symbols=5)
    assert rep.score >= 90
    _, vol = stl_with_volume(lay)
    est = print_estimate(vol)
    assert 10 < est.grams < 200
