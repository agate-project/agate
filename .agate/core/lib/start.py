"""`agate.py start`: what the agent needs at the start of a conversation, and nothing else.

It prints only what needs attention: normally one line, `Reply in: <language>`. Other lines appear only when
something is wrong (MCP config out of date, a missing token, git hooks off, an unapproved project extension, an
oversized memory index, package updates — checked at most once a week). Never more than 8 lines.

`agate.py lang get|set` reads and saves the reply language.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PREFS = Path("memory/local/preferences.md")
PEOPLE = Path("memory/local/people")
PROJECT = Path("memory/shared/project.md")
INDEX = Path("memory/INDEX.md")
STATE = Path("memory/local/state.json")
INDEX_LIMIT = 150
MAX_LINES = 8
UPDATE_EVERY = _dt.timedelta(days=7)


def now() -> _dt.datetime:
    """Current time; tests (and debugging) can pin it with AGATE_NOW=YYYY-MM-DDTHH:MM:SS."""
    fixed = os.environ.get("AGATE_NOW")
    return _dt.datetime.fromisoformat(fixed) if fixed else _dt.datetime.now()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "person"


def frontmatter_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    m = re.search(rf"^{re.escape(key)}:\s*([^\s#]+)", path.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip("\"'") if m else None


def resolve_language(root: Path, person: str | None = None) -> tuple[str | None, str | None]:
    """(language, file it came from). Person → local preference → project default."""
    person = person or os.environ.get("AGATE_PERSON")
    candidates = []
    if person:
        candidates.append((root / PEOPLE / f"{slug(person)}.md", "language"))
    candidates += [(root / PREFS, "language"), (root / PROJECT, "default_language")]
    for path, key in candidates:
        value = frontmatter_value(path, key)
        if value:
            return value, path.relative_to(root).as_posix()
    return None, None


def _set_key(path: Path, key: str, value: str, name: str, description: str) -> None:
    today = now().date().isoformat()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if re.search(rf"^{re.escape(key)}:", text, re.M):
            text = re.sub(rf"^{re.escape(key)}:.*$", f"{key}: {value}", text, count=1, flags=re.M)
        elif text.startswith("---"):
            text = text.replace("---\n", f"---\n{key}: {value}\n", 1)
        else:
            text = f"---\n{key}: {value}\n---\n\n" + text
        text = re.sub(r"^updated:.*$", f"updated: {today}", text, count=1, flags=re.M)
    else:
        text = (f"---\nname: {name}\ndescription: {description}\nupdated: {today}\n{key}: {value}\n---\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def set_language(root: Path, code: str, project: bool = False, person: str | None = None) -> list[str]:
    """Save the reply language. Returns what was written (for the message)."""
    code = code.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", code):
        raise SystemExit(f"'{code}' does not look like a language code (es, en, pt, pt-br…).")
    person = person or os.environ.get("AGATE_PERSON")
    written = []
    if person:
        path = root / PEOPLE / f"{slug(person)}.md"
        _set_key(path, "language", code, f"person-{slug(person)}", f"{person}: working preferences on this machine")
    else:
        path = root / PREFS
        _set_key(path, "language", code, "preferences", "this machine's preferences (reply language)")
    written.append(path.relative_to(root).as_posix())
    if project or not frontmatter_value(root / PROJECT, "default_language"):
        _set_key(root / PROJECT, "default_language", code, "project",
                 "project defaults (reply language for anyone without a saved preference)")
        written.append(PROJECT.as_posix())
        index = root / INDEX
        line = "- [Project defaults](shared/project.md) — default reply language and other project defaults"
        text = index.read_text(encoding="utf-8") if index.is_file() else "# Memory\n"
        if "shared/project.md" not in text:
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")
            written.append(INDEX.as_posix())
    return written


# ---------------------------------------------------------------- checks

def mcp_lines(root: Path) -> list[str]:
    import mcp  # noqa: PLC0415
    import project_extension as px  # noqa: PLC0415
    servers = mcp.load_servers(root)
    if not servers and not px.extension_path(root, "mcp").is_file():
        return []
    lines = []  # missing tokens are reported by env_lines (one place for every variable in use)
    if mcp.is_stale(root):
        lines.append("MCP config out of date: run `python3 .agate/agate.py mcp sync --if-stale`.")
    if mcp.hooks_state(root) == "inactive":
        lines.append("Git hooks are off: run `python3 .agate/agate.py mcp hooks install` and tell the person in one line.")
    if px.status(root, "mcp") == "unapproved":
        lines.append(".agate/project/mcp.py changed (someone else's edit): review it with the person "
                     "(`agate.py mcp extension review`) before approving.")
    return lines


def env_lines(root: Path) -> list[str]:
    """Only variables something in use needs (connectors, skills, tools), plus severe .env/git problems."""
    import env  # noqa: PLC0415
    lines = []
    missing = env.missing_in_use(root)
    if missing:
        lines.append("Missing in .env: " + ", ".join(f"{v} ({'/'.join(o) or 'project'})" for v, o in missing)
                     + ". The person runs `python3 .agate/agate.py env set NAME` (hidden input) or pastes it in .env "
                     "with the editor; never in the chat.")
    if env.in_use(root) or (root / ".env").is_file():
        lines += [a for a in env.git_alerts(root) if (root / ".env").is_file() or "tracked" in a]
    return lines


def tokens_lines(root: Path) -> list[str]:
    import tokens  # noqa: PLC0415
    return tokens.weekly_line(root)


def index_line(root: Path) -> list[str]:
    path = root / INDEX
    if not path.is_file():
        return []
    n = len(path.read_text(encoding="utf-8").splitlines())
    return [f"memory/INDEX.md has {n} lines (limit {INDEX_LIMIT}): condense or group it."] if n > INDEX_LIMIT else []


def update_lines(root: Path) -> list[str]:
    """At most once every 7 days; silent on any failure (offline, no git…)."""
    if os.environ.get("AGATE_OFFLINE"):
        return []
    state_path = root / STATE
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except json.JSONDecodeError:
        state = {}
    last = state.get("last_update_check")
    current = now()
    if last:
        try:
            if current - _dt.datetime.fromisoformat(last) < UPDATE_EVERY:
                return []
        except ValueError:
            pass
    lines = []
    try:
        import packages  # noqa: PLC0415
        rows = [r for r in packages.check_rows(root) if packages.has_update(r)]
        if rows:
            names = ", ".join(("agate" if r["kind"] == "base" else r["name"]) for r in rows[:4])
            more = f" (+{len(rows) - 4})" if len(rows) > 4 else ""
            lines.append(f"Updates available: {names}{more}. Tell the person; `python3 .agate/agate.py check` shows them.")
    except Exception:  # noqa: BLE001  (network or git problems never get in the way)
        pass
    state["last_update_check"] = current.isoformat(timespec="seconds")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return lines


def start_lines(root: Path, person: str | None = None) -> tuple[str | None, list[str]]:
    lang, _ = resolve_language(root, person)
    lines = [f"Reply in: {lang}" if lang else
             "Reply language not saved: detect it from the person's message, reply in it, and save it with "
             "`python3 .agate/agate.py lang set <code>`."]
    try:
        import packages  # noqa: PLC0415
        packages.load_lock(root)
        lines += packages.MIGRATION_NOTES
        packages.MIGRATION_NOTES.clear()
    except Exception:  # noqa: BLE001
        pass
    for check in (env_lines, mcp_lines, index_line, update_lines, tokens_lines):
        try:
            lines += check(root)
        except Exception:  # noqa: BLE001  (a broken check must not break the start)
            pass
    return lang, lines


def cap(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_LINES:
        return lines
    return lines[:MAX_LINES - 1] + [f"(+{len(lines) - MAX_LINES + 1} more: `python3 .agate/agate.py start --all`)"]


# ---------------------------------------------------------------- CLI

def cmd_start(a) -> int:
    root = Path(a.root).resolve()
    lang, lines = start_lines(root, a.person)
    if not a.all:
        lines = cap(lines)
    if a.json:
        print(json.dumps({"language": lang, "lines": lines}, ensure_ascii=False))
    else:
        print("\n".join(lines))
    return 0


def cmd_lang(a) -> int:
    root = Path(a.root).resolve()
    if a.action == "get":
        lang, source = resolve_language(root, a.person)
        print(f"{lang} ({source})" if lang else "not saved")
        return 0 if lang else 1
    if not a.code:
        raise SystemExit("Usage: agate.py lang set <code> [--project] [--person NAME]")
    written = set_language(root, a.code, a.project, a.person)
    print(f"Reply language '{a.code}' saved in: " + ", ".join(written))
    return 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("start", help="what the agent needs at the start of a conversation (quiet otherwise)")
    p.add_argument("--person", help="person's name, if several people share this checkout (or AGATE_PERSON)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="do not cap the output at 8 lines")
    p.set_defaults(func=cmd_start)
    p = sub.add_parser("lang", help="get or save the reply language")
    p.add_argument("action", choices=("get", "set"))
    p.add_argument("code", nargs="?")
    p.add_argument("--project", action="store_true", help="also make it the project default")
    p.add_argument("--person", help="save it for this person (shared checkout)")
    p.set_defaults(func=cmd_lang)
