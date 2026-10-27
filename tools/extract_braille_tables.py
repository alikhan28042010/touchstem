"""Extract uncontracted Russian and Kazakh braille mappings from liblouis tables.

Reads liblouis table files as plain data (no liblouis code is executed) and
writes touchstem/braille_tables.json. Dot 9 in liblouis Cyrillic definitions
is a virtual marker used to separate Cyrillic from Latin letters; it is not a
physical dot, so it is stripped from the output.

Usage: python -I tools/extract_braille_tables.py <liblouis/tables dir> <out.json>
"""
import json
import re
import sys
from pathlib import Path

RULE_RE = re.compile(r"^\s*(lowercase|punctuation|sign|math|litdigit|numsign)\s+(\S+)(?:\s+(\S+))?")


def decode_char(token: str) -> str:
    if token.startswith("\\x"):
        return chr(int(token[2:], 16))
    if token.startswith("\\") and len(token) == 2:
        return token[1]
    return token


def clean_dots(dots: str) -> list[str]:
    cells = []
    for cell in dots.split("-"):
        cell = "".join(sorted(d for d in cell if d in "123456"))
        cells.append(cell if cell else "0")
    return cells


def parse(path: Path) -> dict:
    out = {"letters": {}, "punct": {}, "digits": {}, "numsign": None}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0] if not raw.lstrip().startswith("sign #") else raw
        m = RULE_RE.match(line)
        if not m:
            continue
        opcode, a, b = m.groups()
        if opcode == "numsign":
            out["numsign"] = clean_dots(a)
            continue
        if b is None:
            continue
        ch = decode_char(a)
        if len(ch) != 1:
            continue
        cells = clean_dots(b)
        if opcode == "lowercase":
            out["letters"][ch] = cells
        elif opcode == "litdigit":
            out["digits"][ch] = cells
        else:
            out["punct"][ch] = cells
    return out


def main() -> None:
    tables = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    ru = parse(tables / "ru-litbrl.ctb")
    digits = parse(tables / "litdigits6Dots.uti")["digits"]
    kk_extra = parse(tables / "kk.utb")

    # Russian alphabet only (U+0430..U+044F and ё); drop Old Church Slavonic extras.
    ru_letters = {c: d for c, d in ru["letters"].items() if "а" <= c <= "я" or c == "ё"}
    kk_letters = dict(ru_letters)
    kk_letters.update(kk_extra["letters"])  # Kazakh-specific letters override (e.g. і)
    kk_punct = dict(ru["punct"])
    kk_punct.update(kk_extra["punct"])  # Kazakh uses dots 2356 for parentheses

    result = {
        "_source": "Derived from liblouis tables ru-litbrl.ctb, kk.utb, litdigits6Dots.uti "
                   "(https://github.com/liblouis/liblouis, LGPL-2.1+). Dot 9 markers stripped.",
        "ru": {"letters": ru_letters, "punct": ru["punct"], "digits": digits, "numsign": ru["numsign"]},
        "kk": {"letters": kk_letters, "punct": kk_punct, "digits": digits, "numsign": ru["numsign"]},
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ru letters={len(ru_letters)} kk letters={len(kk_letters)} punct={len(ru['punct'])} digits={len(digits)}")


if __name__ == "__main__":
    main()
