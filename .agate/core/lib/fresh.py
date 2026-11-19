"""Fresh project: set it up silently the first time, and tell the agent once, in one line.

No questionnaire in the base: the agent fills the project description as the person talks about it.
A guided start exists as an optional hub skill (`quick-start`).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
from pathlib import Path

PLACEHOLDER = "Describe here, in two or three lines"
HOOKS_REL = ".agate/core/hooks"
SEVERITY = 4  # same level as start's INFO: useful, never urgent
DIRS = ("memory/shared", "memory/local", "documents", "artifacts")


def _has_placeholder(root: Path) -> bool:
    try:
        return PLACEHOLDER in (root / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _has_project_yml(root: Path) -> bool:
    return (root / "memory" / "shared" / "project.yml").is_file()


def needs_setup(root: Path) -> bool:
    """Silent setup runs while the template placeholder is in AGENTS.md or there is no project.yml."""
    return _has_placeholder(root) or not _has_project_yml(root)


def _saved_something(root: Path) -> bool:
    """A first conversation already happened: a project default or someone's preferences were saved."""
    local = root / "memory" / "local"
    return (_has_project_yml(root) or (local / "preferences.yml").is_file()
            or any((local / "people").glob("*.yml")))


def is_fresh(root: Path) -> bool:
    """Brand-new project: the placeholder is still there AND nothing was saved yet. The line is said in the
    first conversation only: saving the reply language (start asks for it) ends it."""
    return _has_placeholder(root) and not _saved_something(root)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)


def _enable_hooks(root: Path) -> bool:
    """Point git at the base's hooks if nothing else is configured. True when hooks are on."""
    try:
        if _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
            return False
        hooks = root / HOOKS_REL
        if not hooks.is_dir():
            return False
        current = _git(root, "config", "--get", "core.hooksPath").stdout.strip()
        if current.rstrip("/") == HOOKS_REL:
            return True
        if current:  # someone chose other hooks: respect it
            return False
        for hook in hooks.iterdir():
            if hook.is_file():
                try:
                    hook.chmod(hook.stat().st_mode | 0o111)
                except OSError:
                    pass
        return _git(root, "config", "core.hooksPath", HOOKS_REL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def setup(root: Path) -> dict:
    """Idempotent first-run setup. Never raises."""
    done = {"dirs": [], "hooks": False}
    for rel in DIRS:
        d = root / rel
        try:
            if not d.is_dir():
                d.mkdir(parents=True, exist_ok=True)
                done["dirs"].append(rel)
        except OSError:
            pass
    done["hooks"] = _enable_hooks(root)
    state_path = root / "memory" / "local" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        if not isinstance(state, dict):
            state = {}
        if "fresh_setup_at" not in state:
            now = os.environ.get("AGATE_NOW") or _dt.datetime.now().isoformat(timespec="seconds")
            state["fresh_setup_at"] = now
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(state_path)
    except (OSError, ValueError):
        pass
    return done


def attention(root) -> list[dict]:
    """Start's attention provider: one line while the project is fresh, nothing afterwards."""
    try:
        root = Path(root)
        if not (root / "AGENTS.md").is_file() or not needs_setup(root):  # not an Agate project, or done
            return []
        done = setup(root)
        if not is_fresh(root):
            return []
        hooks = " (git hooks on)" if done["hooks"] else ""
        return [{"severity": SEVERITY, "text": (
            f"New Agate project, set up{hooks}. As the person tells you what the project is about, fill the top of "
            "AGENTS.md and memory/shared/project.yml — no questionnaire. Optional guided start: "
            "`python3 .agate/agate.py add quick-start`.")}]
    except Exception:  # noqa: BLE001 - a provider never breaks start
        return []
