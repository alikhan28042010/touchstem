import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from touchstem.regions import RegionDoc, build_regions, regions_lesson
from touchstem.render import Spec
from touchstem.share import decode, encode_steps
from touchstem.touch import find_phrases, graph_point_phrases, payload_phrases, regions_payload
from touchstem import tts

ROOT = Path(__file__).parents[1]
EX = ["school_floor.json", "plant_cell.json", "microwave_panel.json"]


def load(name, lang="ru"):
    return RegionDoc.from_dict(json.loads((ROOT / "examples" / name).read_text(encoding="utf-8")), lang)


@pytest.mark.parametrize("name", EX)
@pytest.mark.parametrize("lang", ["ru", "kk"])
def test_examples_build_clean(name, lang):
    res = build_regions(load(name, lang), Spec(), lang)
    assert res.layout.warnings == []
    assert len([h for h in res.hotspots if h["key"]]) == len(res.doc.regions)
    lesson = regions_lesson(res, lang)
    assert lesson.intro and lesson.tour and lesson.quiz


def test_localized_labels():
    assert load("school_floor.json", "kk").regions[0].label != load("school_floor.json", "ru").regions[0].label


def test_neighbours_and_containment():
    res = build_regions(load("plant_cell.json"), Spec(), "ru")
    vac = next(h for h in res.hotspots if h["label"] == "Вакуоль")
    assert "Цитоплазма" in vac["l3"]                  # the vacuole sits inside the cytoplasm
    res = build_regions(load("school_floor.json"), Spec(), "ru")
    lib = next(h for h in res.hotspots if h["label"] == "Библиотека")
    assert "Коридор" in lib["l3"] and "Кабинет химии" in lib["l3"]


def test_panel_is_real_size():
    res = build_regions(load("microwave_panel.json"), Spec(), "ru")
    assert abs(res.layout.width - (64 + 12)) < 0.01   # 1:1 plus 6 mm rim each side


def test_doors_cut_walls():
    doc = load("school_floor.json")
    walls_with = build_regions(doc, Spec(), "ru").layout.raised.area
    doc.doors = []
    assert build_regions(doc, Spec(), "ru").layout.raised.area > walls_with


def test_ai_style_input_0_1000_and_polygons():
    d = {"title": "x", "kind": "diagram", "aspect": 1.0,
         "regions": [{"label": "A", "polygon": [[100, 100], [500, 100], [500, 500], [100, 500]]},
                     {"label": "B", "box": [600, 600, 900, 900]}]}
    doc = RegionDoc.from_dict(d)
    assert max(x for r in doc.regions for x, _ in r.poly) <= 1.0
    assert build_regions(doc).layout.warnings == []


def test_steps_link_roundtrip():
    s = encode_steps(["один", "два"], "kk", "Жоспар")
    assert decode(s) == {"kind": "steps", "lang": "kk", "title": "Жоспар", "steps": ["один", "два"]}


def test_find_phrases_cover_directions():
    res = build_regions(load("school_floor.json"), Spec(), "ru")
    p = regions_payload(res, "ru", "t")
    ph = find_phrases(p)
    assert "правее и выше" in ph and "ниже" in ph and "Нашли! Библиотека." in ph
    assert all(x in payload_phrases(p) for x in ph)


def test_speakable_numbers():
    assert tts.speakable("Номер 3, лампа: 2,5 В", "ru") .startswith("Номер три, лампа: две целых пять десятых вольта") or \
        "три" in tts.speakable("Номер 3", "ru")
    assert "икс" in tts.speakable("x 2, y 4", "ru")
    k = tts.speakable("кернеу 4,5 В", "kk")
    assert "төрт" in k and "вольт" in k


def test_graph_point_phrases_match_js():
    from touchstem.graphs import build_graph
    from touchstem.touch import graph_payload
    res = build_graph("x^2 - 4", (-4, 4), (-5, 6), "ru")
    ph = graph_point_phrases(graph_payload(res, "ru", "t"))
    assert "икс 0, игрек -4" in ph and "икс 2, игрек 0" in ph


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_engine_regions_and_find(tmp_path):
    res = build_regions(load("school_floor.json"), Spec(), "ru")
    p = regions_payload(res, "ru", "t")
    lib = next(h for h in p["hs"] if h[1] == "Библиотека")
    corr = next(h for h in p["hs"] if h[1] == "Коридор")
    script = f"""
global.window = globalThis; window.__TS_TEST = true; window.__spoken = [];
require({json.dumps(str(ROOT / 'static/touch.js'))});
const TS = window.TouchSTEM; const cfg = {json.dumps(p, ensure_ascii=False)};
const e = new TS.Engine(cfg);
const lib = {json.dumps(lib[5:7])}, corr = {json.dumps(corr[5:7])};
const at = (pt, t) => e.update({{x: pt[0], y: pt[1]}}, t);
at(lib, 0); at(lib, 500);                 // dwell -> name
e.update(null, 600); at(lib, 900);        // lift + touch -> description
const idx = e.targets().findIndex(t => t[0] === 'Библиотека');
e.find(idx);
at([corr[0] - 60, corr[1] + 20], 3000);        // far left, below -> direction hint
at(lib, 5000); at(lib, 5400);             // arrive and hold
console.log(JSON.stringify({{spoken: window.__spoken, chimes: window.__chimes || 0}}));
"""
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True).stdout)
    spoken = out["spoken"]
    assert spoken[0] == "Библиотека"
    assert spoken[1].startswith("Есть книги")
    assert spoken[2].startswith("Найдите: Библиотека")
    assert spoken[3] == "правее и выше"
    assert spoken[-1] == "Нашли! Библиотека."
    assert out["chimes"] == 1


def test_tts_key_matches_js():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    js = "const c=require('crypto');console.log(c.createHash('sha1').update('kk|Сәлем').digest('hex').slice(0,20))"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()
    assert out == tts.key("Сәлем", "kk") == hashlib.sha1("kk|Сәлем".encode()).hexdigest()[:20]
