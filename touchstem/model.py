"""Circuit description (what the AI returns) plus validation and normalisation.

JSON shape:
{
  "title": "Последовательное соединение",
  "nodes": [{"id": "n1", "x": 0, "y": 0}, ...],          # integer grid, y grows downward
  "elements": [{"id": "e1", "type": "resistor", "from": "n1", "to": "n2",
                "label": "R1", "value": "10 Ом"}, ...],
  "notes": "anything the model was unsure about"
}
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .braille import normalize_label
from .components import NAMES, TYPES


class CircuitError(ValueError):
    pass


@dataclass
class Node:
    id: str
    x: int
    y: int


@dataclass
class Element:
    id: str
    type: str
    a: str
    b: str
    label: str = ""
    value: str = ""
    key: int | None = None
    state: str = "closed"          # switches only: "closed" | "open"


@dataclass
class Circuit:
    title: str
    nodes: dict[str, Node]
    elements: list[Element]
    notes: str = ""
    warnings: list[str] = field(default_factory=list)

    # ---------- parsing ----------
    @classmethod
    def from_dict(cls, data: dict) -> "Circuit":
        if not isinstance(data, dict):
            raise CircuitError("ожидался JSON-объект")
        nodes: dict[str, Node] = {}
        for raw in data.get("nodes", []):
            try:
                nid = str(raw["id"])
                nodes[nid] = Node(nid, int(round(float(raw["x"]))), int(round(float(raw["y"]))))
            except (KeyError, TypeError, ValueError) as exc:
                raise CircuitError(f"неверный узел: {raw}") from exc
        if len(nodes) < 2:
            raise CircuitError("в схеме меньше двух узлов")
        elements: list[Element] = []
        warnings: list[str] = []
        for i, raw in enumerate(data.get("elements", [])):
            kind = str(raw.get("type", "other")).lower().strip()
            if kind not in TYPES:
                warnings.append(f"неизвестный тип «{kind}» заменён на «other»")
                kind = "other"
            a, b = str(raw.get("from", "")), str(raw.get("to", ""))
            if a not in nodes or b not in nodes:
                warnings.append(f"элемент {raw.get('id', i)} ссылается на несуществующий узел — пропущен")
                continue
            elements.append(Element(str(raw.get("id", f"e{i + 1}")), kind, a, b,
                                    str(raw.get("label", "") or ""),
                                    normalize_label(str(raw.get("value", "") or "")),
                                    state="open" if str(raw.get("state", "")).lower() == "open" else "closed"))
        if not elements:
            raise CircuitError("в схеме нет элементов")
        c = cls(str(data.get("title", "") or ""), nodes, elements, str(data.get("notes", "") or ""), warnings)
        c.normalize()
        return c

    # ---------- normalisation ----------
    def normalize(self) -> None:
        self._merge_duplicate_nodes()
        self._drop_degenerate()
        self._make_orthogonal()
        self._shift_to_origin()
        self._assign_keys()

    def _merge_duplicate_nodes(self) -> None:
        by_pos: dict[tuple[int, int], str] = {}
        remap: dict[str, str] = {}
        for n in list(self.nodes.values()):
            keep = by_pos.setdefault((n.x, n.y), n.id)
            if keep != n.id:
                remap[n.id] = keep
                del self.nodes[n.id]
        for e in self.elements:
            e.a, e.b = remap.get(e.a, e.a), remap.get(e.b, e.b)

    def _drop_degenerate(self) -> None:
        before = len(self.elements)
        self.elements = [e for e in self.elements if e.a != e.b]
        if len(self.elements) < before:
            self.warnings.append("удалены элементы нулевой длины")

    def _node_at(self, x: int, y: int) -> str:
        for n in self.nodes.values():
            if n.x == x and n.y == y:
                return n.id
        nid = f"bend{len(self.nodes) + 1}"
        while nid in self.nodes:
            nid += "_"
        self.nodes[nid] = Node(nid, x, y)
        return nid

    def _make_orthogonal(self) -> None:
        out: list[Element] = []
        for e in self.elements:
            na, nb = self.nodes[e.a], self.nodes[e.b]
            if na.x == nb.x or na.y == nb.y:
                out.append(e)
                continue
            corner = self._node_at(nb.x, na.y)
            horiz, vert = abs(nb.x - na.x), abs(nb.y - na.y)
            if e.type == "wire":
                out += [Element(e.id + "a", "wire", e.a, corner), Element(e.id + "b", "wire", corner, e.b)]
            elif horiz >= vert:
                out += [Element(e.id, e.type, e.a, corner, e.label, e.value, state=e.state), Element(e.id + "w", "wire", corner, e.b)]
            else:
                out += [Element(e.id + "w", "wire", e.a, corner), Element(e.id, e.type, corner, e.b, e.label, e.value, state=e.state)]
            self.warnings.append(f"элемент {e.id} был по диагонали — проложен под прямым углом")
        self.elements = out

    def _shift_to_origin(self) -> None:
        mx = min(n.x for n in self.nodes.values())
        my = min(n.y for n in self.nodes.values())
        for n in self.nodes.values():
            n.x -= mx
            n.y -= my

    def _assign_keys(self) -> None:
        comps = [e for e in self.elements if e.type != "wire"]

        def pos(e: Element) -> tuple[float, float]:
            a, b = self.nodes[e.a], self.nodes[e.b]
            return ((a.y + b.y) / 2, (a.x + b.x) / 2)

        for k, e in enumerate(sorted(comps, key=pos), start=1):
            e.key = k

    # ---------- helpers ----------
    @property
    def width(self) -> int:
        return max(n.x for n in self.nodes.values())

    @property
    def height(self) -> int:
        return max(n.y for n in self.nodes.values())

    def degree(self, node_id: str) -> int:
        return sum((e.a == node_id) + (e.b == node_id) for e in self.elements)

    def legend(self, lang: str) -> list[tuple[int, str]]:
        rows = []
        for e in sorted((e for e in self.elements if e.key), key=lambda e: e.key):
            text = NAMES[e.type][lang]
            if e.value:
                text += " " + e.value
            rows.append((e.key, text))
        return rows

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "nodes": [{"id": n.id, "x": n.x, "y": n.y} for n in self.nodes.values()],
            "elements": [{"id": e.id, "type": e.type, "from": e.a, "to": e.b, "label": e.label, "value": e.value,
                          **({"state": e.state} if e.type == "switch" else {})}
                         for e in self.elements],
            "notes": self.notes,
        }
