"""Pack a diagram into a short URL parameter (no database needed) and make QR codes.

The QR on the teacher sheet opens the audio guide on a student's phone:
https://touchstem.streamlit.app/?g=<data>
"""
from __future__ import annotations

import base64
import io
import json
import zlib

from .model import Circuit

MAX_PARAM = 2400  # keeps the QR scannable when printed ~35 mm wide


def _pack(obj: dict) -> str:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")


def _unpack(s: str) -> dict:
    if len(s) > 6000:
        raise ValueError("слишком длинная ссылка")
    pad = "=" * (-len(s) % 4)
    raw = zlib.decompress(base64.urlsafe_b64decode(s + pad), bufsize=65536)
    if len(raw) > 60000:
        raise ValueError("слишком большие данные")
    return json.loads(raw.decode("utf-8"))


def encode_circuit(c: Circuit, lang: str) -> str:
    return _pack({
        "k": "c", "l": lang, "t": c.title,
        "n": [[n.id, n.x, n.y] for n in c.nodes.values()],
        "e": [[e.id, e.type, e.a, e.b, e.value, e.state] for e in c.elements],
    })


def encode_graph(formula: str, rng: tuple[float, float, float, float], lang: str, title: str = "") -> str:
    return _pack({"k": "g", "l": lang, "f": formula, "r": list(rng), "t": title})


def decode(s: str) -> dict:
    """Returns {'kind': 'circuit', 'lang', 'circuit': dict} or {'kind': 'graph', 'lang', 'formula', 'range', 'title'}."""
    d = _unpack(s)
    lang = d.get("l", "ru") if d.get("l") in ("ru", "kk") else "ru"
    if d.get("k") == "g":
        r = [float(v) for v in d["r"]][:4]
        return {"kind": "graph", "lang": lang, "formula": str(d["f"])[:120], "range": r, "title": str(d.get("t", ""))}
    circuit = {
        "title": d.get("t", ""),
        "nodes": [{"id": i, "x": x, "y": y} for i, x, y in d["n"]],
        "elements": [{"id": i, "type": t, "from": a, "to": b, "value": v, "state": st}
                     for i, t, a, b, v, st in d["e"]],
    }
    return {"kind": "circuit", "lang": lang, "circuit": circuit}


def guide_url(base: str, param: str) -> str:
    return f"{base.rstrip('/')}/?g={param}"


def qr_png(url: str, box: int = 8) -> bytes:
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_matrix(url: str) -> list[list[bool]]:
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()
