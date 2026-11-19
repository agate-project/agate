"""`agate.py env`: environment variables (API keys, tokens) on demand, without ever showing their values.

- `env add NAME --where "…" --for <package>`: registers a variable the moment something needs it (name and where to
  get it in `.env.example`, an empty line in `.env`, its owner in `.agate/env.json`).
- `env remove NAME | --for <package>`: forgets variables nobody uses anymore.
- `env set NAME`: asks for the value with hidden input and writes `.env` (for a terminal; never through the chat).
- `env check`: validates `.env` without reading values out loud (missing, empty, placeholders, copy-paste mistakes,
  duplicates, known formats, `.env` safe from git; `--live` asks each provider whether the key works).

Values are never printed, not even partially. `--fingerprint` shows the first 6 hex characters of a SHA-256, enough
to tell whether two machines hold the same key.
"""
from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXAMPLE = Path(".env.example")
DOTENV = Path(".env")
OWNERS = Path(".agate/env.json")
VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
PLACEHOLDER_RE = re.compile(
    r"^(x{3,}|\*{3,}|\.{3,}|<[^>]*>|\[[^\]]*\]|changeme|change[-_ ]?me|replace[-_ ]?me|todo|tbd|placeholder|"
    r"insert[-_ ].*|your[-_ ].*|.*your[-_ ]?(api[-_ ]?)?(key|token|secret).*|sk-\.\.\.|none|null)$", re.I)

# Known formats: variable → (public prefix to show, regex the whole value should match).
KNOWN_FORMATS = {
    "ANTHROPIC_API_KEY": ("sk-ant-", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "TAVILY_API_KEY": ("tvly-", r"tvly-[A-Za-z0-9_-]{16,}"),
    "EXA_API_KEY": ("uuid", r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    "OPENAI_API_KEY": ("sk-", r"sk-[A-Za-z0-9_-]{20,}"),
    "GEMINI_API_KEY": ("AIza", r"AIza[A-Za-z0-9_-]{30,}"),
    "GOOGLE_API_KEY": ("AIza", r"AIza[A-Za-z0-9_-]{30,}"),
    "GITHUB_TOKEN": ("ghp_ / github_pat_", r"(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "SLACK_BOT_TOKEN": ("xoxb-", r"xoxb-[A-Za-z0-9-]{20,}"),
}
# Value prefixes that identify a provider whatever the variable is called (only the prefix is ever shown).
KNOWN_PREFIXES = [("sk-ant-", "Anthropic"), ("tvly-", "Tavily"), ("github_pat_", "GitHub"), ("ghp_", "GitHub"),
                  ("xoxb-", "Slack"), ("xoxp-", "Slack"), ("AIza", "Google"), ("sk-", "OpenAI-style")]


# ---------------------------------------------------------------- reading the files (values stay inside)

def read_entries(path: Path) -> tuple[list[dict], list[int]]:
    """Every `NAME=value` line with its raw value and line number, plus 'stray' line numbers (broken pastes)."""
    entries, stray = [], []
    if not path.is_file():
        return entries, stray
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = LINE_RE.match(raw)
        if m:
            entries.append({"name": m.group(1), "raw": m.group(2), "line": n})
        else:
            stray.append(n)
    return entries, stray


def clean_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def names_in(path: Path) -> list[str]:
    seen: list[str] = []
    for e in read_entries(path)[0]:
        if e["name"] not in seen:
            seen.append(e["name"])
    return seen


def values(root: Path) -> dict[str, str]:
    """name → value from `.env` (first definition wins). For other modules; never printed."""
    out: dict[str, str] = {}
    for e in read_entries(root / DOTENV)[0]:
        out.setdefault(e["name"], clean_value(e["raw"]))
    return out


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:6]


def load_owners(root: Path) -> dict:
    path = root / OWNERS
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        return {}


def save_owners(root: Path, data: dict) -> None:
    path = root / OWNERS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def mcp_owners(root: Path) -> dict[str, list[str]]:
    """Variables declared by connectors in `.agate/mcp/servers.json` (they count as 'in use' too)."""
    path = root / ".agate/mcp/servers.json"
    try:
        servers = json.loads(path.read_text(encoding="utf-8")).get("servers", {}) if path.is_file() else {}
    except json.JSONDecodeError:
        servers = {}
    owners: dict[str, list[str]] = {}
    for name, server in servers.items():
        for var in server.get("env", []) or []:
            owners.setdefault(var, []).append(name)
    return owners


def in_use(root: Path) -> dict[str, list[str]]:
    """Variables something in the project uses: name → owners (packages, connectors)."""
    used = {k: list(v.get("for", [])) for k, v in load_owners(root).items()}
    for var, servers in mcp_owners(root).items():
        used.setdefault(var, [])
        used[var] += [s for s in servers if s not in used[var]]
    return used


# ---------------------------------------------------------------- add / remove / set

def _append(path: Path, block: str, header: str = "") -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else header
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + block, encoding="utf-8")


def add(root: Path, name: str, where: str = "", for_: str = "", docs: str = "") -> dict:
    """Register a variable. Idempotent. Returns what changed."""
    if not VAR_RE.match(name):
        raise SystemExit(f"'{name}' does not look like a variable name (UPPER_SNAKE_CASE). Names go here, never values.")
    result = {"name": name, "example": False, "local": False, "owner": False}
    note = f"# {for_ or name}: {where}" if where else f"# {for_ or name}"
    if docs:
        note += f" (docs: {docs})"
    if name not in names_in(root / EXAMPLE):
        _append(root / EXAMPLE, f"{note}\n{name}=\n")
        result["example"] = True
    if name not in names_in(root / DOTENV):
        _append(root / DOTENV, f"# {for_ or name}\n{name}=\n",
                header="# Your values (not committed). Names are in .env.example.\n")
        result["local"] = True
    owners = load_owners(root)
    entry = owners.setdefault(name, {"for": [], "where": where, "added": _dt.date.today().isoformat()})
    if for_ and for_ not in entry["for"]:
        entry["for"].append(for_)
        result["owner"] = True
    if where and not entry.get("where"):
        entry["where"] = where
    save_owners(root, owners)
    return result


def _drop_line(path: Path, name: str, drop_lonely_comment: bool = True) -> bool:
    """Remove `NAME=` lines; also the comment just above when it only described that variable."""
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    changed = False
    i = 0
    while i < len(lines):
        m = LINE_RE.match(lines[i])
        if m and m.group(1) == name:
            changed = True
            if drop_lonely_comment and out and out[-1].lstrip().startswith("#"):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if not LINE_RE.match(nxt):  # nobody else under that comment
                    out.pop()
            i += 1
            continue
        out.append(lines[i])
        i += 1
    if changed:
        path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    return changed


def remove(root: Path, names: list[str], for_: str | None) -> list[str]:
    """Forget variables. With `for_`, only drops that owner and removes variables left without owners."""
    owners = load_owners(root)
    removed = []
    targets = list(names)
    if for_:
        for var, entry in list(owners.items()):
            if for_ in entry.get("for", []):
                entry["for"].remove(for_)
                if not entry["for"]:
                    targets.append(var)
    for var in dict.fromkeys(targets):
        if var in mcp_owners(root) and not for_:
            print(f"{var} is still used by a connector ({', '.join(mcp_owners(root)[var])}); kept.")
            continue
        owners.pop(var, None)
        if _drop_line(root / EXAMPLE, var):
            removed.append(var)
    save_owners(root, owners)
    return removed


def write_value(root: Path, name: str, value: str) -> None:
    """Write NAME=value in `.env` atomically (0600). The value never goes to stdout or logs."""
    if "\n" in value or "\r" in value:
        raise SystemExit("The value contains a line break; paste it again on a single line.")
    if re.search(r"[\s#\"'\\]", value):
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    path = root / DOTENV
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else \
        ["# Your values (not committed). Names are in .env.example."]
    done = False
    for i, line in enumerate(lines):
        m = LINE_RE.match(line)
        if m and m.group(1) == name and not done:
            lines[i] = f"{name}={value}"
            done = True
    if not done:
        lines.append(f"{name}={value}")
    fd, tmp = tempfile.mkstemp(prefix=".env.", dir=str(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------- check

def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None


def git_alerts(root: Path) -> list[str]:
    """Severe problems: `.env` tracked, committed in history, or not ignored. Empty outside a git repo."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if not inside or inside.returncode != 0:
        return []
    alerts = []
    tracked = _git(root, "ls-files", "--error-unmatch", ".env")
    if tracked and tracked.returncode == 0:
        alerts.append("SEVERE: .env is tracked by git. Remove it from the index (`git rm --cached .env`), "
                      "add it to .gitignore and rotate every key in it.")
    history = _git(root, "log", "--all", "--format=%h", "--", ".env")
    if history and history.stdout.strip():
        alerts.append("SEVERE: .env appears in git history. Rotate every key that was in it; cleaning history "
                      "needs a person to decide.")
    ignored = _git(root, "check-ignore", "-q", ".env")
    if ignored and ignored.returncode != 0:
        alerts.append("SEVERE: .env is not in .gitignore. Add it before saving any key.")
    return alerts


def format_note(name: str, value: str) -> str | None:
    known = KNOWN_FORMATS.get(name)
    if known:
        prefix, pattern = known
        return (f"format ok ({prefix}…)" if re.fullmatch(pattern, value)
                else f"unexpected format (expected {prefix}…)")
    for prefix, provider in KNOWN_PREFIXES:
        if value.startswith(prefix):
            return f"looks like a {provider} key ({prefix}…)"
    return None


def load_validators(root: Path) -> dict:
    """NAME → callable(value, timeout) -> (status, code). From core modules (`ENV_VALIDATORS`) and installed
    skills (`.agents/skills/<skill>/env_validators.py` with `VALIDATORS`). Project files are not loaded here."""
    found: dict = {}
    lib = Path(__file__).resolve().parent
    for path in sorted(lib.glob("*.py")):
        if path.stem in ("env", "cli") or path.stem.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "ENV_VALIDATORS" not in text:
            continue
        try:
            module = __import__(path.stem)
            found.update(getattr(module, "ENV_VALIDATORS", {}))
        except Exception:  # noqa: BLE001
            pass
    for path in sorted((root / ".agents/skills").glob("*/env_validators.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"agate_env_validators_{path.parent.name}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            found.update(getattr(module, "VALIDATORS", {}))
        except Exception:  # noqa: BLE001
            pass
    return found


def live_mcp(root: Path, var: str, timeout: float) -> tuple[str, str | None] | None:
    servers = mcp_owners(root).get(var)
    if not servers:
        return None
    try:
        import mcp  # noqa: PLC0415
        ok, _ = mcp.probe_server(root, servers[0], timeout=timeout)
        return ("ok", None) if ok else ("rejected", f"mcp doctor {servers[0]}")
    except Exception:  # noqa: BLE001
        return ("error", None)


def check(root: Path, names: list[str] | None = None, live: bool = False, show_fp: bool = False,
          timeout: float = 15.0) -> dict:
    entries, stray = read_entries(root / DOTENV)
    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)
    example = names_in(root / EXAMPLE)
    wanted = names or list(dict.fromkeys(example + list(by_name)))
    used = in_use(root)
    validators = load_validators(root) if live else {}
    results = []
    for name in wanted:
        r: dict = {"name": name, "issues": [], "used_by": used.get(name, [])}
        defs = by_name.get(name, [])
        if not defs:
            if os.environ.get(name):
                r["status"] = "from environment"
                value = os.environ[name]
            else:
                r["status"] = "missing"
                results.append(r)
                continue
        else:
            raw = defs[0]["raw"]
            value = clean_value(raw)
            if len(defs) > 1:
                r["issues"].append("defined more than once (lines " + ", ".join(str(d["line"]) for d in defs) + ")")
            if raw != raw.strip() and raw.strip():
                r["issues"].append("has surrounding whitespace")
            stripped = raw.strip()
            if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
                r["issues"].append("has surrounding quotes")
            if not value:
                r["status"] = "from environment" if os.environ.get(name) else "empty"
                if r["status"] == "empty":
                    results.append(r)
                    continue
                value = os.environ[name]
            else:
                r["status"] = "set"
        if PLACEHOLDER_RE.match(value):
            r["status"] = "placeholder"
        note = format_note(name, value)
        if note:
            r["format"] = note
        if show_fp:
            r["fp"] = fingerprint(value)
        if live and r["status"] in ("set", "from environment"):
            validator = validators.get(name)
            if validator:
                try:
                    status, code = validator(value, timeout)
                except Exception:  # noqa: BLE001
                    status, code = "error", None
                r["live"] = {"ok": "ok", "rejected": f"rejected ({code})" if code else "rejected",
                             "error": "network error"}.get(status, status)
            else:
                via_mcp = live_mcp(root, name, timeout)
                r["live"] = ("no live check" if via_mcp is None else
                             {"ok": "ok", "rejected": "rejected (" + (via_mcp[1] or "") + ")",
                              "error": "network error"}[via_mcp[0]])
        results.append(r)
    alerts = git_alerts(root)
    if stray:
        alerts.append("Lines that are not NAME=value (a broken paste?): " + ", ".join(map(str, stray)) + ".")
    return {"vars": results, "alerts": alerts}


def problems(report: dict) -> bool:
    bad = {"missing", "empty", "placeholder"}
    return bool(report["alerts"]) or any(
        r["status"] in bad or r["issues"] or str(r.get("live", "")).startswith("rejected")
        or str(r.get("format", "")).startswith("unexpected") for r in report["vars"])


def render(report: dict) -> list[str]:
    lines = list(report["alerts"])
    for r in report["vars"]:
        parts = [r["status"]]
        parts += r["issues"]
        if r.get("format"):
            parts.append(r["format"])
        if r.get("live"):
            parts.append("live: " + r["live"])
        if r.get("fp"):
            parts.append("fp:" + r["fp"])
        owners = f" [{', '.join(r['used_by'])}]" if r["used_by"] else ""
        lines.append(f"{r['name']}{owners}: " + " · ".join(parts))
    if not report["vars"] and not report["alerts"]:
        lines.append("No variables declared (.env.example is empty). Nothing to check.")
    return lines


def missing_in_use(root: Path) -> list[tuple[str, list[str]]]:
    """(name, owners) of variables something uses and that have no value. For `agate.py start`."""
    vals = values(root)
    return [(var, owners) for var, owners in sorted(in_use(root).items())
            if not vals.get(var) and not os.environ.get(var)]



# ---------------------------------------------------------------- keys pasted in the chat

PASTE_PATTERNS = [
    ("Anthropic", r"sk-ant-[A-Za-z0-9_-]{20,}"), ("OpenAI-style", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    ("Tavily", r"tvly-[A-Za-z0-9_-]{16,}"), ("GitHub", r"(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    ("Slack", r"xox[abprs]-[A-Za-z0-9-]{20,}"), ("Google", r"AIza[A-Za-z0-9_-]{30,}"),
    ("AWS", r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), ("Stripe", r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
BLOCK_MESSAGE = ("Your message looks like it contains a {what} key, so it was NOT sent to the model. Treat that key "
                 "as exposed: rotate it at the provider. To store the new one safely, use the env-manager app or a "
                 "terminal: python3 .agate/agate.py env set NAME (hidden input). Never paste keys in the chat.")


def scan_text(text: str) -> list[str]:
    """Providers whose key formats appear in the text (values are never returned)."""
    return [who for who, pat in PASTE_PATTERNS if re.search(pat, text or "")]


def cmd_scan_prompt(a) -> int:
    """Hook entry: reads the harness's JSON from stdin ({"prompt": …}); exit 2 + stderr blocks the message."""
    raw = sys.stdin.read()
    try:
        prompt = json.loads(raw).get("prompt", "")
    except (ValueError, AttributeError):
        prompt = raw
    found = scan_text(prompt)
    if not found:
        return 0
    sys.stderr.write(BLOCK_MESSAGE.format(what=" / ".join(sorted(set(found)))) + "\n")
    return 2

# ---------------------------------------------------------------- CLI

def cmd_env(a) -> int:
    root = Path(a.root).resolve()
    if a.action == "add":
        if not a.names or len(a.names) != 1:
            raise SystemExit("Usage: agate.py env add NAME --where \"where to get it\" --for <package>")
        r = add(root, a.names[0], a.where or "", a.for_ or "", a.docs or "")
        done = []
        if r["example"]:
            done.append("added to .env.example")
        if r["local"]:
            done.append("empty line in .env")
        print(f"{r['name']}: " + (", ".join(done) if done else "already registered") +
              f". The person sets the value with `python3 .agate/agate.py env set {r['name']}` (terminal, hidden "
              f"input) or pastes it in .env with the editor; never in the chat.")
        return 0
    if a.action == "remove":
        if not a.names and not a.for_:
            raise SystemExit("Usage: agate.py env remove NAME… | --for <package> [--yes]")
        if not a.yes:
            target = ", ".join(a.names) if a.names else f"variables only used by '{a.for_}'"
            print(f"Would remove {target} from .env.example and .agate/env.json. Confirm with the person, then "
                  "rerun with --yes.")
            return 3
        removed = remove(root, a.names or [], a.for_)
        print("Removed from .env.example: " + (", ".join(removed) if removed else "nothing"))
        if removed:
            if a.clear_local:
                for var in removed:
                    _drop_line(root / DOTENV, var)
                print("Their lines in .env were cleared too.")
            else:
                print("Their values are still in .env; offer to clear them (`env remove … --yes --clear-local`).")
        return 0
    if a.action == "set":
        if not a.names or len(a.names) != 1:
            raise SystemExit("Usage: agate.py env set NAME [--stdin]")
        name = a.names[0]
        if not VAR_RE.match(name):
            raise SystemExit(f"'{name}' does not look like a variable name.")
        value = (sys.stdin.readline() if a.stdin else getpass.getpass(f"{name} (input hidden): ")).strip()
        if not value:
            print("Nothing saved (empty input).")
            return 1
        write_value(root, name, value)
        print(f"saved: {name} (fp:{fingerprint(value)})")
        if name not in names_in(root / EXAMPLE):
            print(f"Note: {name} is not in .env.example; register it with `agate.py env add {name} --where … --for …`.")
        for alert in git_alerts(root):
            print(alert)
        return 0
    # check
    report = check(root, a.names or None, a.live, a.fingerprint)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(render(report)))
    return 1 if problems(report) else 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("env", help="environment variables on demand: add, remove, set (hidden input), check "
                                   "(never shows values)")
    p.add_argument("action", choices=("add", "remove", "set", "check"))
    p.add_argument("names", nargs="*", metavar="NAME")
    p.add_argument("--where", help="add: where to get it (goes as a comment in .env.example)")
    p.add_argument("--for", dest="for_", metavar="PACKAGE", help="add/remove: what uses it (connector, skill…)")
    p.add_argument("--docs", help="add: documentation link")
    p.add_argument("--yes", action="store_true", help="remove: apply")
    p.add_argument("--clear-local", action="store_true", help="remove: also clear the lines in .env")
    p.add_argument("--live", action="store_true", help="check: ask each provider whether the key works")
    p.add_argument("--fingerprint", action="store_true", help="check: show fp:xxxxxx (first 6 hex of SHA-256)")
    p.add_argument("--stdin", action="store_true", help="set: read the value from stdin (for apps; never echoed)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_env)
    q = sub.add_parser("scan-prompt", help="hook: block a chat message that contains an API key (reads JSON on stdin)")
    q.set_defaults(func=cmd_scan_prompt)
