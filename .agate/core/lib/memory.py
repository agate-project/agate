"""Memory entries as commands: add, update, remove, list, check (Claude Code auto-memory conventions).

One fact per file in memory/shared/ (team, committed) or memory/local/ (this machine), with frontmatter
`name`, `description`, `updated`, optional `type`, and one line per entry in memory/INDEX.md:
`- [Title](path) — description`. The commands keep file and index in sync so nothing depends on the model
remembering the format. `attention()` feeds `agate.py start` only when something is actionable.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

INDEX = Path("memory/INDEX.md")
SCOPES = ("shared", "local")
SECTION_FOR = {"shared": "Shared (`shared/`)", "local": "Local (`local/`, this machine)"}
CMD = "python3 .agate/agate.py"
DEFAULTS = {"memory_index_lines": 150, "memory_stale_days": 120, "memory_nudge_commits": 8}
_LINK = re.compile(r"^\s*-\s*\[(?P<title>[^\]]*)\]\((?P<path>[^)]+)\)\s*(?:[—-]\s*(?P<desc>.*))?$")
SKIP_DIRS = {"log", "people", ".cache", "previews"}


class UserError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def today() -> str:
    return os.environ.get("AGATE_TODAY") or _dt.date.today().isoformat()


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not s:
        raise UserError("The name needs at least one letter or digit.")
    return s[:60]


def title_of(slug_: str) -> str:
    return slug_.replace("-", " ").capitalize()


def settings(root: Path) -> dict:
    data = dict(DEFAULTS)
    try:
        conf = config.read_config(root)
    except Exception:  # noqa: BLE001
        conf = {}
    for key in DEFAULTS:
        if isinstance(conf.get(key), int):
            data[key] = conf[key]
    return data


def split_frontmatter(text: str) -> tuple[dict | None, str]:
    """(fields, body). fields is None when there is no frontmatter block."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end < 0:
        return None, text
    fields = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    rest = text[end + 4:]
    return fields, rest[1:] if rest.startswith("\n") else rest


def render_file(fields: dict, body: str) -> str:
    order = ["name", "description", "updated", "type"]
    keys = order + [k for k in fields if k not in order]
    head = "\n".join(f"{k}: {fields[k]}" for k in keys if fields.get(k) not in (None, ""))
    body = body.strip("\n")
    return f"---\n{head}\n---\n" + (body + "\n" if body else "")


def entry_files(root: Path) -> list[Path]:
    """Memory entry files (.md) under memory/shared and memory/local, skipping logs, people and tool state."""
    files = []
    for scope in SCOPES:
        base = root / "memory" / scope
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(base)
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
                continue
            files.append(path)
    return files


def find(root: Path, name: str) -> Path | None:
    s = slug(name)
    for scope in SCOPES:
        path = root / "memory" / scope / f"{s}.md"
        if path.is_file():
            return path
    for path in entry_files(root):
        fields, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        if path.stem == s or (fields and slug(fields.get("name", "") or "x") == s):
            return path
    return None


def index_rel(root: Path, path: Path) -> str:
    return path.relative_to(root / "memory").as_posix()


def read_index(root: Path) -> list[str]:
    path = root / INDEX
    if not path.is_file():
        return ["# Project memory", "", "One line per entry: `- [Title](path) — what it is about`.", ""]
    return path.read_text(encoding="utf-8").splitlines()


def write_index(root: Path, lines: list[str]) -> None:
    path = root / INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip("\n") + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _norm(target: str) -> str:
    return target.strip().lstrip("./").removeprefix("memory/")


def set_index_line(root: Path, path: Path, description: str, section: str | None = None,
                   title: str | None = None) -> None:
    rel = index_rel(root, path)
    lines = read_index(root)
    for i, line in enumerate(lines):
        m = _LINK.match(line)
        if m and _norm(m.group("path")) == rel:
            old_title = m.group("title")
            lines[i] = f"- [{title or old_title}]({rel}) — {description}"
            write_index(root, lines)
            return
    scope = rel.split("/", 1)[0]
    heading = "## " + (section or SECTION_FOR.get(scope, scope))
    new = f"- [{title or title_of(path.stem)}]({rel}) — {description}"
    for i, line in enumerate(lines):
        if line.strip().lower() == heading.lower() or (not section and line.startswith("## ")
                                                         and f"`{scope}/`" in line):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            lines.insert(j, new)
            write_index(root, lines)
            return
    while lines and not lines[-1].strip():
        lines.pop()
    lines += ["", heading, new]
    write_index(root, lines)


def drop_index_line(root: Path, rel: str) -> bool:
    lines = read_index(root)
    kept = [ln for ln in lines if not ((m := _LINK.match(ln)) and _norm(m.group("path")) == rel)]
    if len(kept) != len(lines):
        write_index(root, kept)
        return True
    return False


def read_body(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    return value


# ---------------------------------------------------------------- commands

def add(root: Path, name: str, description: str, type_: str | None = None, scope: str = "shared",
        body: str | None = None, section: str | None = None, force: bool = False) -> Path:
    if scope not in SCOPES:
        raise UserError("--scope must be shared or local.")
    if not description or not description.strip():
        raise UserError("--description is required (one line: it decides whether anyone opens the entry).")
    s = slug(name)
    existing = find(root, s)
    if existing and not force:
        raise UserError(f"'{s}' already exists ({existing.relative_to(root).as_posix()}): use "
                        f"`{CMD} memory update {s}` (or --force to replace it).")
    path = root / "memory" / scope / f"{s}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = {"name": s, "description": " ".join(description.split()), "updated": today(), "type": type_ or ""}
    path.write_text(render_file(fields, body or ""), encoding="utf-8")
    set_index_line(root, path, fields["description"], section)
    return path


def update(root: Path, name: str, description: str | None = None, body: str | None = None,
           append: str | None = None, type_: str | None = None) -> Path:
    path = find(root, name)
    if not path:
        raise UserError(f"No memory entry '{slug(name)}': create it with `{CMD} memory add`.")
    fields, old_body = split_frontmatter(path.read_text(encoding="utf-8"))
    fields = fields or {"name": path.stem}
    if description:
        fields["description"] = " ".join(description.split())
    if type_:
        fields["type"] = type_
    new_body = old_body if body is None else body
    if append:
        new_body = new_body.rstrip("\n") + ("\n\n" if new_body.strip() else "") + append.strip() + "\n"
    fields["updated"] = today()
    fields.setdefault("name", path.stem)
    path.write_text(render_file(fields, new_body), encoding="utf-8")
    if fields.get("description"):
        set_index_line(root, path, fields["description"])
    return path


def remove(root: Path, name: str, yes: bool = False) -> tuple[Path, bool]:
    path = find(root, name)
    if not path:
        raise UserError(f"No memory entry '{slug(name)}'.")
    if not yes:
        return path, False
    rel = index_rel(root, path)
    path.unlink()
    drop_index_line(root, rel)
    return path, True


def entries(root: Path) -> list[dict]:
    out = []
    for path in entry_files(root):
        fields, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        rel = index_rel(root, path)
        out.append({"path": path, "rel": rel, "scope": rel.split("/", 1)[0], "fields": fields or {}})
    return out


def check(root: Path) -> dict:
    """Problems, by kind. Never raises for content problems."""
    conf = settings(root)
    found = entries(root)
    indexed: dict[str, str] = {}
    broken = []
    index_lines = [ln for ln in read_index(root) if ln.strip()]
    for line in index_lines:
        m = _LINK.match(line)
        if not m:
            continue
        target = m.group("path").strip()
        if "://" in target:
            continue
        rel = _norm(target)
        indexed[rel] = line
        if not (root / "memory" / rel).exists():
            broken.append(rel)
    orphans = [e["rel"] for e in found if e["rel"] not in indexed]
    invalid = []
    names: dict[str, list[str]] = {}
    stale = []
    limit = _dt.date.fromisoformat(today()) - _dt.timedelta(days=conf["memory_stale_days"])
    for e in found:
        f = e["fields"]
        missing = [k for k in ("name", "description", "updated") if not f.get(k)]
        bad_date = False
        if f.get("updated"):
            try:
                if _dt.date.fromisoformat(f["updated"][:10]) < limit:
                    stale.append(e["rel"])
            except ValueError:
                bad_date = True
        if missing or bad_date:
            invalid.append(e["rel"] + " (" + ", ".join(missing + (["updated date"] if bad_date else [])) + ")")
        names.setdefault(f.get("name") or e["path"].stem, []).append(e["rel"])
    duplicates = [f"{n}: " + ", ".join(p) for n, p in names.items() if len(p) > 1]
    long_index = len(index_lines) if len(index_lines) > conf["memory_index_lines"] else 0
    return {"orphans": orphans, "broken": broken, "invalid": invalid, "duplicates": duplicates,
            "long_index": long_index, "stale": stale}


def fix(root: Path) -> list[str]:
    """Add missing index lines and drop broken ones. Never deletes memory files."""
    done = []
    report = check(root)
    for rel in report["broken"]:
        if drop_index_line(root, rel):
            done.append(f"removed broken index line: {rel}")
    for rel in report["orphans"]:
        path = root / "memory" / rel
        fields, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        desc = (fields or {}).get("description") or "(no description yet: add one with memory update)"
        set_index_line(root, path, desc)
        done.append(f"added index line: {rel}")
    return done


# ---------------------------------------------------------------- start integration

def _git(root: Path, *args: str) -> str:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def work_commits_since_memory(root: Path) -> int:
    """Commits touching artifacts/ or documents/ since the last commit that touched memory/."""
    last = _git(root, "log", "-1", "--format=%H", "--", "memory").strip()
    rng = [f"{last}..HEAD"] if last else ["HEAD"]
    out = _git(root, "log", "--format=%H", *rng, "--", "artifacts", "documents")
    return len([ln for ln in out.splitlines() if ln.strip()])


def attention(root) -> list[dict]:
    root = Path(root)
    try:
        if not (root / "memory").is_dir():
            return []
        items = []
        report = check(root)
        parts = []
        for key, label in (("orphans", "not in the index"), ("broken", "broken index links"),
                           ("invalid", "bad frontmatter"), ("duplicates", "duplicate names")):
            if report[key]:
                parts.append(f"{len(report[key])} {label}")
        if parts:
            items.append({"severity": 5, "text": f"memory: {', '.join(parts)} → run `{CMD} memory check --fix` "
                                                 "(and fill what it can't)"})
        n = work_commits_since_memory(root)
        if n >= settings(root)["memory_nudge_commits"]:
            items.append({"severity": 6, "text": f"{n} work commits since the last memory update → consider saving "
                                                 f"decisions with `{CMD} memory add`"})
        return items
    except Exception:  # noqa: BLE001
        return []


def index_block(root: Path, max_lines: int | None = None) -> list[str]:
    """What `start` prints so reading the index and running start is one action."""
    path = root / INDEX
    if not path.is_file():
        return []
    def is_entry(line: str) -> bool:
        # Structured files (preferences, project defaults: .yml/.json) are already surfaced by start itself.
        m = _LINK.match(line)
        return bool(m) and not m.group("path").strip().lower().endswith((".yml", ".yaml", ".json"))

    lines = path.read_text(encoding="utf-8").splitlines()
    entries_ = [ln for ln in lines if is_entry(ln)]
    if not entries_:
        return []
    if max_lines is None:
        try:
            value = config.read_config(root).get("memory_index_inline_lines")
        except Exception:  # noqa: BLE001
            value = None
        max_lines = value if isinstance(value, int) else 40
    body, section = [], None
    for ln in lines:
        if ln.startswith("## "):
            section = ln
            continue
        if is_entry(ln) or (ln.startswith("  ") and body):
            if section:
                body.append(section)
                section = None
            body.append(ln)
    if len(body) > max_lines:
        return [f"Memory index: memory/INDEX.md ({len(entries_)} entries) — read it."]
    return ["Memory index:"] + body


# ---------------------------------------------------------------- CLI

def _say_check(root: Path, report: dict) -> int:
    rows = []
    for key, label in (("orphans", "not in the index"), ("broken", "index line points to a missing file"),
                       ("invalid", "missing or bad frontmatter"), ("duplicates", "duplicate name")):
        rows += [f"{label}: {item}" for item in report[key]]
    if report["long_index"]:
        rows.append(f"index has {report['long_index']} lines (limit {settings(root)['memory_index_lines']}): "
                    "condense or group it")
    stale = report["stale"]
    if not rows and not stale:
        print("memory: ok")
        return 0
    for row in rows:
        print(row)
    if stale:
        shown = ", ".join(stale[:5]) + (f" +{len(stale) - 5} more" if len(stale) > 5 else "")
        print(f"stale (informational, check they are still true): {shown}")
    return 1 if rows else 0


def cmd_memory(a) -> int:
    root = Path(a.root).resolve()
    try:
        if a.action == "add":
            if not a.name:
                raise UserError("Usage: agate.py memory add NAME --description \"…\"")
            path = add(root, a.name, a.description or "", a.type, a.scope, read_body(a.body), a.section, a.force)
            print(f"saved: {path.relative_to(root).as_posix()} (+ index line)")
        elif a.action == "update":
            if not a.name:
                raise UserError("Usage: agate.py memory update NAME [--description …] [--body …] [--append …]")
            path = update(root, a.name, a.description, read_body(a.body), a.append, a.type)
            print(f"updated: {path.relative_to(root).as_posix()}")
        elif a.action == "remove":
            if not a.name:
                raise UserError("Usage: agate.py memory remove NAME [--yes]")
            path, done = remove(root, a.name, a.yes)
            rel = path.relative_to(root).as_posix()
            print(f"removed: {rel} (+ index line)" if done else f"would remove {rel} and its index line; "
                                                                   "add --yes to apply")
            return 0 if done else 3
        elif a.action == "list":
            days = a.stale
            limit = (_dt.date.fromisoformat(today()) - _dt.timedelta(days=days)) if days else None
            rows = 0
            for e in entries(root):
                if a.scope and e["scope"] != a.scope:
                    continue
                f = e["fields"]
                upd = f.get("updated", "?")
                if limit:
                    try:
                        if _dt.date.fromisoformat(upd[:10]) >= limit:
                            continue
                    except ValueError:
                        pass
                print(f"{f.get('name') or e['path'].stem} · {e['scope']} · {upd} · {f.get('description', '')}")
                rows += 1
            if not rows:
                print("no entries")
        elif a.action == "check":
            if a.fix:
                for line in fix(root):
                    print(line)
            return _say_check(root, check(root))
    except UserError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("memory", help="memory entries: add, update, remove, list, check (keeps file and index in sync)")
    p.add_argument("action", choices=("add", "update", "remove", "list", "check"))
    p.add_argument("name", nargs="?", metavar="NAME")
    p.add_argument("--description", help="one line; it decides whether anyone opens the entry")
    p.add_argument("--type", help="optional, free (decision, finding, person, data…)")
    p.add_argument("--scope", choices=SCOPES, default=None, help="shared (team, default) or local (this machine)")
    p.add_argument("--body", help="text of the entry, or - to read it from stdin")
    p.add_argument("--append", help="update: add a paragraph at the end")
    p.add_argument("--section", help="add: index section heading (default: by scope)")
    p.add_argument("--force", action="store_true", help="add: replace an existing entry")
    p.add_argument("--yes", action="store_true", help="remove: apply")
    p.add_argument("--fix", action="store_true", help="check: add missing index lines, drop broken ones")
    p.add_argument("--stale", type=int, metavar="DAYS", help="list: only entries not updated in DAYS")

    def run(a):
        if a.action == "add" and a.scope is None:
            a.scope = "shared"
        return cmd_memory(a)

    p.set_defaults(func=run)
