import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from touchstem.graphs import build_graph
from touchstem.model import Circuit
from touchstem.render import build_diagram
from touchstem.share import _unpack
from touchstem.touch import circuit_payload, fits_mat, graph_payload, mat_pdf, mat_svg, pack, say

ROOT = Path(__file__).parents[1]


def load(name):
    return Circuit.from_dict(json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8")))


def test_hotspots_cover_every_numbered_element():
    c = load("parallel")
    lay = build_diagram(c)
    keyed = {e.id for e in c.elements if e.key}
    assert keyed <= {h["id"] for h in lay.hotspots}
    assert all(0 <= h["x"] <= lay.width and 0 <= h["y"] <= lay.height for h in lay.hotspots)


def test_switch_toggle_announces_changes_ru_and_kk():
    c = load("parallel")
    lay = build_diagram(c)
    ru = circuit_payload(c, lay, "ru")
    assert ru["st"] == 1 and len(ru["tg"]) == 2
    assert "погасла" in ru["tg"][1][0] and "загорелась" in ru["tg"][0][0]
    kk = circuit_payload(c, lay, "kk")
    assert "сөнді" in kk["tg"][1][0]


def test_what_if_removing_one_parallel_lamp():
    c = load("parallel")
    p = circuit_payload(c, build_diagram(c), "ru")
    lamp = next(h for h in p["hs"] if "лампа" in h[5])
    assert "321 миллиампер" in lamp[7][1]          # the other lamp keeps working
    assert lamp[8] == [0, 1]                         # dark with switch open, lit when closed


def test_payload_roundtrip_and_size():
    c = load("series")
    p = circuit_payload(c, build_diagram(c), "kk")
    s = pack(p)
    assert _unpack(s) == json.loads(json.dumps(p))
    assert len(s) < 2000


def test_speakable_units():
    assert say(0.1875, "А") == "188 миллиампер"
    assert say(4.5, "В") == "4,5 вольт"


def test_mat_outputs():
    c = load("series")
    lay = build_diagram(c)
    assert fits_mat(lay)
    svg = mat_svg(lay)
    assert svg.count('fill="black"') == 4 and 'stroke-dasharray' in svg
    assert mat_svg(lay, include_sheet=True).count('fill="black"') > 20
    assert mat_pdf(lay, c.title, "https://example.org/x").startswith(b"%PDF")


def test_graph_payload_has_curve_samples():
    r = build_graph("x^2 - 4", (-4, 4), (-5, 6))
    p = graph_payload(r, "ru")
    assert len(p["cv"]) == 161 and p["zs"] == [-2.0, 2.0]


@pytest.mark.skipif(os.environ.get("E2E") != "1" or not shutil.which("node"), reason="set E2E=1 for the browser test")
def test_fake_camera_end_to_end(tmp_path):
    """Synthetic tilted camera video -> real touch.html in Chromium -> spoken phrases."""
    timeline = tmp_path / "t.json"
    timeline.write_text('[[1.0,null],[1.3,"e3"],[0.5,null],[0.8,"e3"],[0.5,null],[1.3,"e2"],[0.5,null],'
                        '[0.8,"e2"],[0.5,null],[0.8,"e2"],[1.0,null]]')
    video = tmp_path / "cam.y4m"
    subprocess.run([sys.executable, "-I", str(ROOT / "tools/fake_camera.py"), str(ROOT / "examples/series.json"),
                    str(video), str(timeline)], check=True, capture_output=True)
    c = load("series")
    payload = pack(circuit_payload(c, build_diagram(c), "ru"))
    out = subprocess.run(["/usr/bin/python3", str(ROOT / "tools/e2e_camera.py"), str(ROOT / "static"), payload,
                          str(video), "13"], check=True, capture_output=True, text=True).stdout
    spoken = json.loads(out[out.index("{"):])["spoken"]
    assert "номер 3, лампа" in spoken
    assert any("Лампа 3 погасла" in s for s in spoken)
