"""Project settings in `.agate/config.yml` (project layer: `agate.py update` never overwrites it).

A tiny, safe reader: flat `key: value` lines, `#` comments, booleans, numbers and quoted strings. No YAML library,
no nesting, nothing executed.
"""
from __future__ import annotations

import re
from pathlib import Path

CONFIG = Path(".agate/config.yml")
DEFAULTS = {"external_artifacts": False}
_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(.*)$")


def _strip_comment(value: str) -> str:
    quote = None
    for i, ch in enumerate(value):
        if ch in "\"'" and quote in (None, ch):
            quote = None if quote else ch
        elif ch == "#" and quote is None and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value.strip()


def parse_value(raw: str):
    value = _strip_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("", "null", "~", "none"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse(text: str) -> dict:
    data: dict = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        m = _LINE.match(line)
        if m:
            data[m.group(1)] = parse_value(m.group(2))
    return data


def read_config(root: Path) -> dict:
    path = root / CONFIG
    data = dict(DEFAULTS)
    if path.is_file():
        data.update(parse(path.read_text(encoding="utf-8")))
    return data
