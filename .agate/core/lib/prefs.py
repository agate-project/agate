"""Short, structured preferences in flat YAML (memory/local and memory/shared).

- `memory/local/preferences.yml`: this machine's person (single-person machine).
- `memory/local/people/<name>.yml`: one file per person when several people share a checkout
  (`AGATE_PERSON=<name>` or `--person`).
- `memory/shared/project.yml`: project defaults (`default_language`, …).

Fields (all optional): name, language, style (one line), notes (path to a longer .md, read only when needed),
preview_identity, consent_<thing> (date the person acknowledged a risk notice, e.g. consent_env_manager).
Long text goes in a .md referenced by `notes:`; JSON is only for tool state (state.json, chats.json…).

Read with the safe flat reader of config.py; written by `write()` here (quoted when needed, atomic).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

LOCAL = Path("memory/local/preferences.yml")
PEOPLE = Path("memory/local/people")
PROJECT = Path("memory/shared/project.yml")
INDEX = Path("memory/INDEX.md")
OLD_LOCAL = Path("memory/local/preferences.md")
OLD_PROJECT = Path("memory/shared/project.md")
KEY_ORDER = ("name", "language", "default_language", "style", "notes", "preview_identity")
MEMORY_KEYS = ("name", "description", "updated", "type")  # frontmatter keys of a memory file, not preferences
_SAFE = re.compile(r"^[^\s\"'#:{}\[\],&*!|>%@`][^#:]*$")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "person"


def person_name(person: str | None = None) -> str | None:
    return (person or os.environ.get("AGATE_PERSON") or "").strip() or None


def person_path(person: str | None = None) -> Path:
    """Where this person's preferences live (relative to the project root)."""
    name = person_name(person)
    return PEOPLE / f"{slug(name)}.yml" if name else LOCAL


def read(path: Path) -> dict:
    if not path.is_file():
        return {}
    return config.parse(path.read_text(encoding="utf-8"))


def _fmt(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    needs_quotes = (not _SAFE.match(text) or text.lower() in ("true", "false", "yes", "no", "on", "off", "null", "~")
                    or re.fullmatch(r"-?\d+(\.\d+)?", text) is not None or text != text.strip())
    return '"' + text.replace('"', "'") + '"' if needs_quotes else text


def write(path: Path, data: dict, header: str = "") -> None:
    keys = [k for k in KEY_ORDER if k in data] + sorted(k for k in data if k not in KEY_ORDER)
    lines = [f"# {line}" for line in header.splitlines()] if header else []
    lines += [f"{k}: {_fmt(data[k])}" for k in keys if data[k] is not None]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def update(root: Path, rel: Path, header: str = "", **values) -> dict:
    path = root / rel
    data = read(path)
    data.update({k: v for k, v in values.items() if v is not None})
    write(path, data, header or _header_for(rel))
    return data


def _header_for(rel: Path) -> str:
    if rel == PROJECT:
        return "Project defaults (committed). Short values only; long notes go in a .md referenced by notes:."
    return "Preferences of the person using this machine (not committed). Short values; long notes in a .md (notes:)."


# ---------------------------------------------------------------- migration from v0.4.0 (.md with frontmatter)

def _split_frontmatter(text: str) -> tuple[dict, str] | None:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    return (config.parse(m.group(1)), m.group(2)) if m else None


def _migrate_one(root: Path, md: Path, yml: Path) -> str | None:
    src, dst = root / md, root / yml
    if not src.is_file() or dst.is_file():
        return None
    parsed = _split_frontmatter(src.read_text(encoding="utf-8"))
    if not parsed:
        return None
    front, body = parsed
    values = {k: v for k, v in front.items() if k not in MEMORY_KEYS or (k == "name" and md.parent == PEOPLE)}
    if not values:
        return None
    if body.strip():
        keep = {k: front[k] for k in MEMORY_KEYS if k in front}
        head = "---\n" + "".join(f"{k}: {v}\n" for k, v in keep.items()) + "---\n" if keep else ""
        src.write_text(head + body.lstrip("\n"), encoding="utf-8")
        values["notes"] = md.as_posix()
    else:
        src.unlink()
    write(dst, values, _header_for(yml))
    index = root / INDEX
    if index.is_file():
        text = index.read_text(encoding="utf-8")
        old = md.relative_to("memory").as_posix()
        if old in text and not body.strip():
            index.write_text(text.replace(old, yml.relative_to("memory").as_posix()), encoding="utf-8")
    return f"{md.as_posix()} → {yml.as_posix()}" + (" (text kept as notes)" if body.strip() else "")


def migrate(root: Path) -> list[str]:
    """Convert v0.4.0 preference files (.md frontmatter) to .yml once. Returns one note per converted file."""
    done = [_migrate_one(root, OLD_LOCAL, LOCAL), _migrate_one(root, OLD_PROJECT, PROJECT)]
    people = root / PEOPLE
    if people.is_dir():
        for md in sorted(people.glob("*.md")):
            rel = md.relative_to(root)
            done.append(_migrate_one(root, rel, rel.with_suffix(".yml")))
    return [d for d in done if d]


# ---------------------------------------------------------------- what start and lang need

def person(root: Path, name: str | None = None) -> dict:
    """The current person's preferences (people/<name>.yml when named, else preferences.yml)."""
    data = read(root / person_path(name))
    if name := person_name(name):
        data.setdefault("name", name)
    return data


def project(root: Path) -> dict:
    return read(root / PROJECT)


def language(root: Path, name: str | None = None) -> tuple[str | None, str | None]:
    """(language, file) — person → this machine → project default."""
    candidates = []
    if person_name(name):
        candidates.append((person_path(name), "language"))
    candidates += [(LOCAL, "language"), (PROJECT, "default_language")]
    for rel, key in candidates:
        value = read(root / rel).get(key)
        if value:
            return str(value), rel.as_posix()
    return None, None
