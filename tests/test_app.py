from streamlit.testing.v1 import AppTest


def test_app_example_flow():
    at = AppTest.from_file("../app.py", default_timeout=60)
    at.run()
    assert not at.exception
    example = [b for b in at.button if b.label.startswith("Пример: series")][0]
    example.click().run()
    assert not at.exception
    assert any("Тактильная версия" in s.value for s in at.subheader)
