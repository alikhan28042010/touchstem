from streamlit.testing.v1 import AppTest


def _app():
    at = AppTest.from_file("../app.py", default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def test_circuit_example_flow():
    at = _app()
    at.pills[0].set_value("Последовательная цепь").run()
    assert not at.exception, at.exception
    assert any("Тактильный лист" in m.value for m in at.markdown)
    labels = [b.label for b in at.get("download_button")]
    assert "Лист учителя, PDF" in labels and "Схема, STL" in labels


def test_graph_flow():
    at = _app()
    at.segmented_control[0].set_value("graph").run()
    assert not at.exception, at.exception
    assert any("Тактильный лист" in m.value for m in at.markdown)


def test_bad_formula_shows_error():
    at = _app()
    at.segmented_control[0].set_value("graph").run()
    at.text_input[0].set_value("import os").run()
    assert at.error, "expected an error message"


def test_guide_route():
    from touchstem.model import Circuit
    from touchstem.share import encode_circuit
    import json
    from pathlib import Path
    c = Circuit.from_dict(json.loads((Path(__file__).parents[1] / "examples/series.json").read_text(encoding="utf-8")))
    at = AppTest.from_file("../app.py", default_timeout=120)
    at.query_params["g"] = encode_circuit(c, "kk")
    at.run()
    assert not at.exception, at.exception


def test_regions_example_flow():
    at = _app()
    at.segmented_control[0].set_value("regions").run()
    assert not at.exception, at.exception
    at.pills[0].set_value("План школы").run()
    assert not at.exception, at.exception
    assert any("Тактильный лист" in m.value for m in at.markdown)
    labels = [b.label for b in at.get("download_button")]
    assert "Схема, STL" in labels
