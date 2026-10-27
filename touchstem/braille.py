"""Uncontracted Russian / Kazakh braille for short tactile-graphics labels.

Mappings come from liblouis tables (see braille_tables.json "_source").
Simplifications, documented for teachers to verify:
  * Text is lowercased: no capital sign (common for tactile-graphic keys).
  * Latin letters are not supported in labels: they are reported as warnings
    and skipped, because Russian/Kazakh braille needs context rules for them.
  * Numbers: number sign (3456) + digit cells; a decimal comma/point inside a
    number is dot 2 (liblouis "midnum"); a comma right after a number is 6-2.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

LANGS = ("ru", "kk")


@lru_cache(maxsize=1)
def _tables() -> dict:
    return json.loads((Path(__file__).with_name("braille_tables.json")).read_text(encoding="utf-8"))


@dataclass
class BrailleResult:
    cells: list[str]               # each cell = dot string like "135"; "0" = blank cell (space)
    warnings: list[str] = field(default_factory=list)

    @property
    def unicode(self) -> str:
        return "".join(cell_to_unicode(c) for c in self.cells)


def cell_to_unicode(cell: str) -> str:
    code = 0x2800
    for d in cell:
        if d in "123456":
            code |= 1 << (int(d) - 1)
    return chr(code)


def translate(text: str, lang: str = "ru") -> BrailleResult:
    if lang not in LANGS:
        raise ValueError(f"unsupported language: {lang}")
    t = _tables()[lang]
    letters, punct, digits, numsign = t["letters"], t["punct"], t["digits"], t["numsign"]
    text = normalize_label(text).lower()
    cells: list[str] = []
    warnings: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isdigit():
            cells.extend(numsign)
            while i < n and (text[i].isdigit() or (text[i] in ",." and i + 1 < n and text[i + 1].isdigit())):
                cells.extend(digits[text[i]] if text[i].isdigit() else ["2"])
                i += 1
            if i < n and text[i] == ",":
                cells.extend(["6", "2"])  # endnum comma
                i += 1
            continue
        if ch.isspace():
            if cells and cells[-1] != "0":
                cells.append("0")
        elif ch in letters:
            cells.extend(letters[ch])
        elif ch in punct:
            cells.extend(punct[ch])
        elif "a" <= ch <= "z":
            warnings.append(f"латинская буква «{ch}» пропущена — проверьте подпись у тифлопедагога")
        else:
            warnings.append(f"символ «{ch}» не поддерживается и пропущен")
        i += 1
    while cells and cells[-1] == "0":
        cells.pop()
    return BrailleResult(cells, warnings)


UNIT_MAP = [
    (r"kΩ|kOhm|kohm", "кОм"), (r"MΩ|MOhm", "МОм"), (r"Ω|Ohm|ohm", "Ом"),
    (r"(?<=\d)\s*mA\b", " мА"), (r"(?<=\d)\s*A\b", " А"),
    (r"(?<=\d)\s*mV\b", " мВ"), (r"(?<=\d)\s*kV\b", " кВ"), (r"(?<=\d)\s*V\b", " В"),
    (r"(?<=\d)\s*(µF|uF|mkF)\b", " мкФ"), (r"(?<=\d)\s*nF\b", " нФ"), (r"(?<=\d)\s*F\b", " Ф"),
    (r"(?<=\d)\s*W\b", " Вт"), (r"(?<=\d)\s*Hz\b", " Гц"),
]


def normalize_label(text: str) -> str:
    """Convert Latin unit symbols to Cyrillic and keep a space between numbers and units."""
    s = text.strip()
    for pat, rep in UNIT_MAP:
        s = re.sub(pat, rep, s)
    s = re.sub(r"(?<=\d)(?=[^\d\s,.\-])", " ", s)  # 10Ом -> 10 Ом
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def has_latin(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", normalize_label(text)))
