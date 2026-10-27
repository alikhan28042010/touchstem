"""Photo of a circuit diagram -> Circuit JSON, using Gemini vision.

The model only *reads* the diagram (parse step). Drawing is done by our own
renderer, so the tactile output never contains invented shapes.
"""
from __future__ import annotations

import json
import re

from .components import TYPES

DEFAULT_MODEL = "gemini-2.5-flash"

PROMPT = f"""You convert a photo or scan of a school electric circuit diagram into JSON.
The diagram may come from a Kazakh or Russian physics textbook (IEC/GOST symbols:
resistor = rectangle, lamp = circle with X, cell = long thin + short thick line).

Return ONLY JSON with this shape:
{{
  "title": "short title in the language of the textbook, or empty",
  "nodes": [{{"id": "n1", "x": 0, "y": 0}}],
  "elements": [{{"id": "e1", "type": "resistor", "from": "n1", "to": "n2", "label": "R1", "value": "10 Ом"}}],
  "notes": "anything unclear, in Russian; empty if all clear"
}}

Rules:
1. Nodes are points on an integer grid that reproduces the diagram's layout
   (x grows to the right, y grows downward). Use a coarse grid: typically 0..4.
   Leave at least 2 grid steps for any edge that holds a component.
2. Every element connects exactly two nodes that share the same x OR the same y.
   Corners of wires are nodes. Junctions (where 3+ wires meet) are nodes.
3. Wire segments are elements with "type": "wire".
4. "type" must be one of: {", ".join(TYPES)}.
   Use "cell" for one galvanic cell, "battery" for several cells drawn together.
   For cell/battery, "from" MUST be the + terminal (long thin plate), "to" the - terminal.
   For a switch add "state": "open" if it is drawn open, otherwise "closed".
5. "label" is the designator printed next to the symbol (R1, L, K, A, V...), "value"
   is the printed value with unit (e.g. "4,5 В", "10 Ом"). Empty string if absent.
6. Do not invent components. If part of the image is unreadable, describe it in "notes".
"""


class AIError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("модель не вернула JSON")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AIError(f"не удалось разобрать JSON: {exc}") from exc


def parse_circuit_image(image_bytes: bytes, mime_type: str, api_key: str, model: str = DEFAULT_MODEL) -> dict:
    """Call Gemini and return the raw circuit dict (validate with Circuit.from_dict)."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise AIError("не установлен пакет google-genai") from exc
    if not api_key:
        raise AIError("нет GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    try:
        resp = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), PROMPT],
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        )
    except Exception as exc:  # network, quota, bad key
        raise AIError(f"ошибка запроса к Gemini: {exc}") from exc
    return _extract_json(resp.text or "")


GRAPH_PROMPT = """You read a photo of a school math function graph or its formula.
Return ONLY JSON: {"formula": "x^2 - 4", "x_min": -4, "x_max": 4, "y_min": -5, "y_max": 6, "title": "", "notes": ""}
- formula uses only x, numbers, + - * / ^ ( ), sin cos tan sqrt abs log exp pi.
- If the formula is printed, copy it. If only the curve is drawn, infer the simplest school formula that fits.
- Axis limits: the visible range of the axes in the picture.
- notes: in Russian, anything uncertain."""


def parse_graph_image(image_bytes: bytes, mime_type: str, api_key: str, model: str = DEFAULT_MODEL) -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover
        raise AIError("не установлен пакет google-genai") from exc
    if not api_key:
        raise AIError("нет GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    try:
        resp = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), GRAPH_PROMPT],
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        )
    except Exception as exc:
        raise AIError(f"ошибка запроса к Gemini: {exc}") from exc
    return _extract_json(resp.text or "")
