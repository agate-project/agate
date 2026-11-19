"""`agate.py start`: what the agent needs at the start of a conversation, and nothing else.

Output contract (≤ 10 lines; a section appears only when it has something to say):

    Reply in: es
    Person: Alex · prefers being asked before assumptions (more: memory/local/people/alex.md)
    Last session (2026-11-18): chose proposal 2 → artifacts/2026-11/2026-11-18-rewards.html
    No native web search here → use the web-research skill
    Skills: canvas — …; web-research — …          (only in harnesses that don't load Agent Skills natively)
    Attention:
    - <problem> → <action> (<guide>)                (most severe first)

When nothing needs attention, the output is a single line: `Reply in: <language>`.
`agate.py lang get|set` reads and saves the reply language (memory/local/*.yml, memory/shared/project.yml).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prefs  # noqa: E402

INDEX = Path("memory/INDEX.md")
CHATS = Path("memory/local/chats.json")
LOG_DIR = Path("memory/shared/log")
CAPABILITIES = Path("memory/local/capabilities.json")
INDEX_LIMIT = 150
MAX_LINES = 10
LAST_SESSION_DAYS = 14
NATIVE_SKILLS = {"claude", "codex", "gemini", "opencode"}  # harnesses that load Agent Skills by themselves
HARNESS_KEYS = {"claude": "claude-code", "gemini": "gemini-cli", "codex": "codex", "opencode": "opencode"}
CMD = "python3 .agate/agate.py"

# Severity order for Attention bullets (lower = shown first).
SEVERE, SECURITY, MISSING, CONFIG, INFO, MEMORY, CONTEXT, UPDATES = range(8)


def now() -> _dt.datetime:
    """Current time; tests (and debugging) can pin it with AGATE_NOW=YYYY-MM-DDTHH:MM:SS."""
    fixed = os.environ.get("AGATE_NOW")
    return _dt.datetime.fromisoformat(fixed) if fixed else _dt.datetime.now()


def slug(name: str) -> str:
    return prefs.slug(name)


def resolve_language(root: Path, person: str | None = None) -> tuple[str | None, str | None]:
    return prefs.language(root, person)


def set_language(root: Path, code: str, project: bool = False, person: str | None = None) -> list[str]:
    """Save the reply language. Returns what was written (for the message)."""
    code = code.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", code):
        raise SystemExit(f"'{code}' does not look like a language code (es, en, pt, pt-br…).")
    prefs.migrate(root)
    rel = prefs.person_path(person)
    name = prefs.person_name(person)
    prefs.update(root, rel, language=code, **({"name": name} if name else {}))
    written = [rel.as_posix()]
    if project or not prefs.project(root).get("default_language"):
        prefs.update(root, prefs.PROJECT, default_language=code)
        written.append(prefs.PROJECT.as_posix())
        index = root / INDEX
        line = "- [Project defaults](shared/project.yml) — default reply language and other project defaults"
        text = index.read_text(encoding="utf-8") if index.is_file() else "# Memory\n"
        if "shared/project.yml" not in text:
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")
            written.append(INDEX.as_posix())
    return written


# ---------------------------------------------------------------- context about the person and the project

def harness() -> str | None:
    forced = os.environ.get("AGATE_HARNESS")
    if forced:
        return forced
    try:
        import mcp  # noqa: PLC0415
        return mcp.current_harness()
    except Exception:  # noqa: BLE001
        return None


def person_line(root: Path, person: str | None) -> list[str]:
    data = prefs.person(root, person)
    style, notes = data.get("style"), data.get("notes")
    if not style and not notes:
        return []
    parts = [str(data["name"])] if data.get("name") else []
    if style:
        parts.append(str(style))
    line = "Person: " + " · ".join(parts) if parts else "Person:"
    return [line + (f" (more: {notes})" if notes else "")]


def _recent(date_text: str, current: _dt.datetime) -> bool:
    try:
        day = _dt.date.fromisoformat(date_text[:10])
    except ValueError:
        return False
    return (current.date() - day).days <= LAST_SESSION_DAYS


def last_session_line(root: Path) -> list[str]:
    current = now()
    path = root / CHATS
    if path.is_file():
        try:
            chats = json.loads(path.read_text(encoding="utf-8")).get("chats", [])
        except (ValueError, OSError):
            chats = []
        noted = [c for c in chats if c.get("summary")]
        if noted:
            c = max(noted, key=lambda x: x.get("updated", ""))
            if _recent(c.get("updated", ""), current):
                produced = (c.get("produced") or [None])[0]
                return [f"Last session ({c['updated'][:10]}): {c['summary']}" + (f" → {produced}" if produced else "")]
    logs = sorted((root / LOG_DIR).glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md")) if (root / LOG_DIR).is_dir() \
        else []
    for log in reversed(logs):
        if not _recent(log.stem, current):
            break
        for raw in log.read_text(encoding="utf-8").splitlines():
            if raw.lstrip().startswith("#"):  # headings (usually just the date) say nothing new
                continue
            text = raw.strip().lstrip("-* ").strip()
            if text and not text.startswith("---") and not re.match(r"^\w+:\s", text):
                return [f"Last session ({log.stem}): {text[:160]} → {log.relative_to(root).as_posix()}"]
    return []


def web_search_line(root: Path) -> list[str]:
    h = harness()
    path = root / CAPABILITIES
    if not h or not path.is_file():
        return []
    try:
        caps = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    prefix = HARNESS_KEYS.get(h, h) + "/"
    mine = [v for k, v in caps.items() if k.startswith(prefix) and isinstance(v, dict)]
    if mine and not any(v.get("native_search") for v in mine):
        return ["No native web search here → use the web-research skill"]
    return []


def skills_line(root: Path) -> list[str]:
    if harness() in NATIVE_SKILLS:
        return []
    items = []
    for skill in sorted((root / ".agents/skills").glob("*/SKILL.md")):
        m = re.search(r"^description:\s*(.+)$", skill.read_text(encoding="utf-8", errors="replace"), re.M)
        desc = (m.group(1).strip().strip("\"'") if m else "")
        desc = desc if len(desc) <= 60 else desc[:57].rstrip() + "…"
        items.append(f"{skill.parent.name} — {desc}" if desc else skill.parent.name)
    if not items:
        return []
    more = f"; +{len(items) - 8} more (.agents/skills/)" if len(items) > 8 else ""
    return ["Skills: " + "; ".join(items[:8]) + more]


# ---------------------------------------------------------------- attention (each item carries its action)

def installed_apps(root: Path) -> set[str]:
    try:
        import packages  # noqa: PLC0415
        pk = packages.load_lock(root)["packages"]
    except Exception:  # noqa: BLE001
        return set()
    return {e["name"] for e in pk.values() if e.get("kind") == "app" and (root / ".agate/apps" / e["name"]).is_dir()}


def env_items(root: Path) -> list[tuple[int, str]]:
    """Only variables something in use needs, plus severe .env/git problems."""
    import env  # noqa: PLC0415
    items = []
    if env.in_use(root) or (root / ".env").is_file():
        for alert in env.git_alerts(root):
            if (root / ".env").is_file() or "tracked" in alert:
                items.append((SEVERE, alert.removeprefix("SEVERE: ") + " (.agate/core/guides/secrets.md)"))
    missing = env.missing_in_use(root)
    if missing:
        names = ", ".join(f"{v} ({'/'.join(o) or 'project'})" for v, o in missing)
        if "env-manager" in installed_apps(root):
            owners = sorted({o for _, os_ in missing for o in os_} or {"project"})
            action = "; ".join(f"python3 .agate/apps/env-manager/run.py --for {o}" for o in owners[:3])
            items.append((MISSING, f"Missing in .env: {names} → ask the person to open the key manager: `{action}`"))
        else:
            first = missing[0][0]
            items.append((MISSING, f"Missing in .env: {names} → ask the person to run `{CMD} env set {first}` "
                                   "(hidden input) or paste it in .env with the editor; never in the chat"))
    return items


def mcp_items(root: Path) -> list[tuple[int, str]]:
    import mcp  # noqa: PLC0415
    import project_extension as px  # noqa: PLC0415
    servers = mcp.load_servers(root)
    if not servers and not px.extension_path(root, "mcp").is_file():
        return []
    items = []
    if px.status(root, "mcp") == "unapproved":
        items.append((SECURITY, ".agate/project/mcp.py changed (someone else's edit) → review it with the person "
                                f"(`{CMD} mcp extension review`) before approving"))
    if mcp.is_stale(root):
        items.append((CONFIG, f"MCP config out of date → `{CMD} mcp sync --if-stale`"))
    if mcp.hooks_state(root) == "inactive":
        items.append((CONFIG, f"Git hooks are off → `{CMD} mcp hooks install`, then tell the person in one line"))
    return items


def index_items(root: Path) -> list[tuple[int, str]]:
    path = root / INDEX
    if not path.is_file():
        return []
    n = len(path.read_text(encoding="utf-8").splitlines())
    if n <= INDEX_LIMIT:
        return []
    return [(MEMORY, f"memory/INDEX.md has {n} lines (limit {INDEX_LIMIT}) → condense or group it "
                     "(.agate/core/guides/memory-format.md)")]


def tokens_items(root: Path) -> list[tuple[int, str]]:
    import tokens  # noqa: PLC0415
    lines = tokens.weekly_line(root)
    if not lines:
        return []
    suffix = " (report: python3 .agate/apps/context-meter/run.py)" if "context-meter" in installed_apps(root) else ""
    return [(CONTEXT, line.rstrip(".") + " (.agate/core/guides/context-budget.md)" + suffix) for line in lines]


def update_items(root: Path) -> list[tuple[int, str]]:
    import packages  # noqa: PLC0415
    line = packages.update_notice(root, offline=bool(os.environ.get("AGATE_OFFLINE")))
    return [(UPDATES, line)] if line else []


def migration_items(root: Path) -> list[tuple[int, str]]:
    items = [(INFO, f"Preferences moved to YAML: {note}") for note in prefs.migrate(root)]
    try:
        import packages  # noqa: PLC0415
        packages.load_lock(root)
        items += [(INFO, note) for note in packages.MIGRATION_NOTES]
        packages.MIGRATION_NOTES.clear()
    except Exception:  # noqa: BLE001
        pass
    return items


def provider_items(root: Path) -> list[tuple[int, str]]:
    """Optional attention providers: any module in core/lib (or an installed app's attention.py) that defines
    `attention(root) -> [{"severity": int, "text": str}]`. Failures are swallowed: a provider never breaks start."""
    import importlib  # noqa: PLC0415
    import importlib.util  # noqa: PLC0415
    lib = Path(__file__).resolve().parent
    modules = []
    for path in sorted(lib.glob("*.py")):
        if path.stem in ("start", "cli") or path.stem.startswith("_"):
            continue
        try:
            if "def attention(" not in path.read_text(encoding="utf-8", errors="replace"):
                continue
            modules.append(importlib.import_module(path.stem))
        except Exception:  # noqa: BLE001
            continue
    for app in sorted(installed_apps(root)):
        path = root / ".agate/apps" / app / "attention.py"
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"agate_app_{app.replace('-', '_')}_attention", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules.append(module)
        except Exception:  # noqa: BLE001
            continue
    items = []
    for module in modules:
        try:
            for entry in module.attention(root) or []:
                text = str(entry.get("text", "")).strip()
                if text:
                    items.append((int(entry.get("severity", INFO)), text))
        except Exception:  # noqa: BLE001
            continue
    return items


CHECKS = (migration_items, env_items, mcp_items, index_items, tokens_items, update_items, provider_items)


def collect(root: Path, person: str | None = None) -> dict:
    lang, _ = (None, None)
    attention: list[tuple[int, str]] = []
    for check in CHECKS[:1]:  # migrations first: later sections read the migrated files
        try:
            attention += check(root)
        except Exception:  # noqa: BLE001  (a broken check must not break the start)
            pass
    lang, _ = resolve_language(root, person)
    head = [f"Reply in: {lang}" if lang else
            "Reply language not saved: detect it from the person's message, reply in it, and save it with "
            f"`{CMD} lang set <code>`."]
    for section in (person_line, last_session_line, web_search_line, skills_line):
        try:
            head += section(root, person) if section is person_line else section(root)
        except Exception:  # noqa: BLE001
            pass
    for check in CHECKS[1:]:
        try:
            attention += check(root)
        except Exception:  # noqa: BLE001
            pass
    attention.sort(key=lambda item: item[0])
    return {"language": lang, "head": head, "attention": [text for _, text in attention]}


def render(data: dict, all_lines: bool = False) -> list[str]:
    lines = list(data["head"])
    bullets = list(data["attention"])
    if not bullets:
        return lines
    room = MAX_LINES - len(lines) - 1
    if not all_lines and len(bullets) > room:
        keep = max(room - 1, 0)
        bullets = bullets[:keep] + [f"+{len(data['attention']) - keep} more: `{CMD} start --all`"]
    return lines + ["Attention:"] + [f"- {b}" for b in bullets]


def start_lines(root: Path, person: str | None = None) -> tuple[str | None, list[str]]:
    """Compatibility helper: (language, rendered lines uncapped)."""
    data = collect(root, person)
    return data["language"], render(data, all_lines=True)


# ---------------------------------------------------------------- CLI

HOOK_WINDOW_SECONDS = 15 * 60


def _hook_mark_path(root: Path) -> Path:
    return root / "memory" / "local" / "start-hook.json"


def _harness_id() -> str:
    if os.environ.get("AGATE_HARNESS"):
        return os.environ["AGATE_HARNESS"]
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude-code"
    return "other"


def _hook_ran_recently(root: Path) -> bool:
    try:
        mark = json.loads(_hook_mark_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if mark.get("harness") != _harness_id():
        return False
    now = float(os.environ.get("AGATE_NOW_TS", _dt.datetime.now().timestamp()))
    return 0 <= now - float(mark.get("at", 0)) < HOOK_WINDOW_SECONDS


def _mark_hook(root: Path) -> None:
    path = _hook_mark_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        now = float(os.environ.get("AGATE_NOW_TS", _dt.datetime.now().timestamp()))
        path.write_text(json.dumps({"at": now, "harness": _harness_id()}), encoding="utf-8")
    except OSError:
        pass


def cmd_start(a) -> int:
    root = Path(a.root).resolve()
    if not a.hook and not a.json and not a.all and _hook_ran_recently(root):
        print("Already loaded at session start by the hook (see above).")
        return 0
    data = collect(root, a.person)
    lines = render(data, a.all)
    if a.hook:
        _mark_hook(root)
        lines = ["(Agate start, loaded by the session hook: don't run it again.)"] + lines
    if a.json:
        print(json.dumps({"language": data["language"], "head": data["head"], "attention": data["attention"],
                          "lines": lines}, ensure_ascii=False))
    else:
        print("\n".join(lines))
    return 0


def cmd_lang(a) -> int:
    root = Path(a.root).resolve()
    if a.action == "get":
        prefs.migrate(root)
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
    p.add_argument("--all", action="store_true", help=f"do not cap the output at {MAX_LINES} lines")
    p.add_argument("--hook", action="store_true", help="called by the harness's session-start hook")
    p.set_defaults(func=cmd_start)
    p = sub.add_parser("lang", help="get or save the reply language")
    p.add_argument("action", choices=("get", "set"))
    p.add_argument("code", nargs="?")
    p.add_argument("--project", action="store_true", help="also make it the project default")
    p.add_argument("--person", help="save it for this person (shared checkout)")
    p.set_defaults(func=cmd_lang)
