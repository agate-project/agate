"""Load a project's own extension of an Agate tool, safely.

A project may add `.agate/project/<tool>.py` (for example `.agate/project/mcp.py`) to extend
`.agate/core/lib/<tool>.py` without editing base files (which `sync.py` overwrites). The base tool calls the
extension's optional hooks at fixed points (Template Method). `.agate/project/` is never touched by `sync.py`.

Security: an extension is code that runs on this machine, sometimes from git hooks right after a `git pull`.
So it only runs once approved:
- the approved sha256 of each extension lives in `memory/local/approvals.json` (local, not committed);
- it is approved automatically when the change is yours: uncommitted local changes, the last commit that touched it
  was made with your `git config user.email`, or the folder is not a git repository;
- otherwise (someone else changed it) it is NOT run until a person reviews it and approves it
  (`python3 .agate/core/lib/<tool>.py extension review|approve`).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

APPROVALS_REL = Path("memory/local/approvals.json")


def extension_path(root: Path, tool: str) -> Path:
    return root / ".agate" / "project" / f"{tool}.py"


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _approvals(root: Path) -> dict:
    path = root / APPROVALS_REL
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        return {}


def _save_approval(root: Path, rel: str, digest: str, how: str) -> None:
    data = _approvals(root)
    data[rel] = {"sha256": digest, "commit": _git(root, "log", "-1", "--format=%H", "--", rel) or "",
                 "approved": _dt.datetime.now().isoformat(timespec="seconds"), "how": how}
    path = root / APPROVALS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def is_own_change(root: Path, rel: str) -> bool:
    """True when the current version of the file is the user's own work (safe to approve without asking)."""
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return True  # no git: nothing arrives by pull
    if _git(root, "status", "--porcelain", "--", rel):
        return True  # uncommitted (or untracked) local changes
    me = (_git(root, "config", "user.email") or "").lower()
    author = (_git(root, "log", "-1", "--format=%ae", "--", rel) or "").lower()
    return bool(me) and me == author


def status(root: Path, tool: str) -> str:
    """'absent', 'approved', 'own' (approvable automatically) or 'unapproved'."""
    path = extension_path(root, tool)
    digest = file_hash(path)
    if digest is None:
        return "absent"
    rel = path.relative_to(root).as_posix()
    if _approvals(root).get(rel, {}).get("sha256") == digest:
        return "approved"
    return "own" if is_own_change(root, rel) else "unapproved"


def approve(root: Path, tool: str, how: str = "manual") -> bool:
    path = extension_path(root, tool)
    digest = file_hash(path)
    if digest is None:
        return False
    _save_approval(root, path.relative_to(root).as_posix(), digest, how)
    return True


def review(root: Path, tool: str) -> str:
    """Diff since the last approved version (or the whole file when there is none)."""
    path = extension_path(root, tool)
    if not path.is_file():
        return f"No {path.relative_to(root).as_posix()} in this project."
    rel = path.relative_to(root).as_posix()
    commit = _approvals(root).get(rel, {}).get("commit")
    if commit:
        diff = _git(root, "diff", commit, "--", rel)
        if diff is not None:
            return diff or "(no changes since the approved commit; only uncommitted changes, if any)"
    return path.read_text(encoding="utf-8")


def load_project_extension(root: Path, tool: str, inject: dict | None = None):
    """Return (module or None, status). Never runs an unapproved extension.

    `inject` adds names to the module before it runs (e.g. {"mcp": <the base tool module>}).
    """
    state = status(root, tool)
    if state == "absent":
        return None, state
    if state == "unapproved":
        return None, state
    if state == "own":
        approve(root, tool, how="auto: own change")
        state = "approved"
    path = extension_path(root, tool)
    spec = importlib.util.spec_from_file_location(f"agate_project_{tool}", path)
    module = importlib.util.module_from_spec(spec)
    for key, value in (inject or {}).items():
        setattr(module, key, value)
    spec.loader.exec_module(module)
    return module, state
