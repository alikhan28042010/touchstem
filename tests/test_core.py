import json
from pathlib import Path

import pytest

from touchstem.braille import translate, normalize_label
from touchstem.model import Circuit, CircuitError
from touchstem.render import build_diagram, build_legend, to_stl, to_svg

EX = Path(__file__).parents[1] / "examples"


def test_russian_letters_and_numbers():
    r = translate("лампа 4,5 В", "ru")
    assert r.unicode == "⠇⠁⠍⠏⠁⠀⠼⠙⠂⠑⠀⠺"
    assert not r.warnings


def test_kazakh_specific_letters():
    assert translate("әғқңөұүһі", "kk").unicode == "⠜⠻⠹⠩⠣⠬⠌⠧⠽"


def test_latin_is_reported_not_guessed():
    r = translate("R1", "ru")
    assert r.warnings and "латин" in r.warnings[0]


def test_units_normalized():
    assert normalize_label("10Ω") == "10 Ом"
    assert normalize_label("4,5V") == "4,5 В"


def test_diagonal_element_becomes_orthogonal():
    c = Circuit.from_dict({"nodes": [{"id": "a", "x": 0, "y": 0}, {"id": "b", "x": 2, "y": 2}],
                           "elements": [{"id": "e", "type": "resistor", "from": "a", "to": "b"}]})
    for e in c.elements:
        na, nb = c.nodes[e.a], c.nodes[e.b]
        assert na.x == nb.x or na.y == nb.y


def test_bad_input_raises():
    with pytest.raises(CircuitError):
        Circuit.from_dict({"nodes": [], "elements": []})


@pytest.mark.parametrize("name", ["series", "parallel"])
@pytest.mark.parametrize("lang", ["ru", "kk"])
def test_examples_render(name, lang):
    c = Circuit.from_dict(json.loads((EX / f"{name}.json").read_text(encoding="utf-8")))
    lay = build_diagram(c, lang=lang)
    leg, uni = build_legend(c, lang)
    assert lay.width <= 200.5 and lay.dots
    assert to_svg(lay).startswith("<svg")
    assert len(to_stl(lay)) > 10_000
    assert uni.count("\n") == len(c.legend(lang))


def test_ai_output_with_fence_and_messy_data():
    from touchstem.ai import _extract_json
    text = '```json\n{"nodes":[{"id":"a","x":0,"y":0},{"id":"b","x":3,"y":1},{"id":"c","x":0,"y":0}],' \
           '"elements":[{"id":"e1","type":"Resistor","from":"a","to":"b","value":"2kΩ"},' \
           '{"id":"e2","type":"transistor","from":"b","to":"c"}]}\n```'
    c = Circuit.from_dict(_extract_json(text))
    assert c.elements[0].type == "resistor" and c.elements[0].value == "2 кОм"
    assert any("other" in w for w in c.warnings)
    build_diagram(c)
