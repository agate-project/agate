"""Packages: the base, extensions and skills, recorded in ONE lock (`.agate/lock.json`).

Every package is a folder taken from a source (a git repo or a local path), pinned to a commit and fingerprinted:
- base and extensions are synced with `sync.py` (owned files + blocks);
- skills are copied with `skills_sync.py` into `.agents/skills/<name>/`.
This module holds what they share (fetch, hash, lock) and the user-facing commands that cover all of them:
`check`, `update`, `add`, `remove`, `search`, `list`, `verify`, `doctor`, `sources`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LOCK = Path(".agate/lock.json")
OLD_SKILLS_LOCK = Path(".agate/skills.lock.json")
MIGRATION_NOTES: list[str] = []


# ---------------------------------------------------------------- shared helpers

def read_json(path: Path, default=None):
    if not path.is_file():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def is_url(value: str) -> bool:
    return "://" in value or value.startswith("git@")


def git_commit(path: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def fetch(repo: str, sub: str, tmp: Path, ref: str | None = None) -> tuple[Path, str | None]:
    """Make `repo` (path or URL) available locally. Returns (folder of the sub-path, commit).

    For URLs with a sub-path only that folder is downloaded (partial clone + sparse checkout); if the server or the
    local git doesn't support it, it falls back to a full shallow clone. With `ref` (a release tag or branch name) the
    content comes from that ref, never from the branch tip; local repos are then cloned too, so the working tree of the
    source is not what gets installed.
    """
    if not is_url(repo) and not ref:
        root = Path(repo).expanduser().resolve()
        commit = git_commit(root) if (root / ".git").exists() else None
        return (root / sub if sub else root), commit
    dest = tmp / "src"
    branch = ["--branch", ref] if ref else []
    source = repo if is_url(repo) else str(Path(repo).expanduser().resolve())

    def run(*args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    if sub:
        try:
            run("clone", "--quiet", "--filter=blob:none", "--no-checkout", "--depth", "1", *branch, source, str(dest))
            run("-C", str(dest), "sparse-checkout", "set", sub)
            run("-C", str(dest), "checkout", "--quiet")
        except subprocess.CalledProcessError:
            shutil.rmtree(dest, ignore_errors=True)
            run("clone", "--quiet", "--depth", "1", *branch, source, str(dest))
    else:
        run("clone", "--quiet", "--depth", "1", *branch, source, str(dest))
    return (dest / sub if sub else dest), git_commit(dest)


# ---------------------------------------------------------------- supply chain: release tags and scripts

SCRIPT_SUFFIXES = (".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ps1", ".bat", ".cmd")
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def is_script_path(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return rel.endswith(SCRIPT_SUFFIXES) or "/hooks/" in f"/{rel}"


def script_files(folder: Path) -> list[str]:
    """Code files a package would add to the project: script suffixes, executables and git hooks."""
    out = []
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if not p.is_file() or rel.startswith(".git/") or "/__pycache__/" in f"/{rel}" or rel.endswith(".pyc"):
            continue
        if is_script_path(rel) or os.access(p, os.X_OK):
            out.append(rel)
    return out


def changed_scripts(old: Path, new: Path) -> list[str]:
    """Scripts added, removed or changed between an installed folder and its new version."""
    def files(folder: Path) -> dict[str, str]:
        return {rel: hashlib.sha256((folder / rel).read_bytes()).hexdigest() for rel in script_files(folder)}
    a, b = files(old), files(new)
    return sorted(r for r in set(a) | set(b) if a.get(r) != b.get(r))


def _norm_repo(repo: str) -> str:
    repo = (repo or "").strip().rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo and not is_url(repo):
        repo = str(Path(repo).expanduser().resolve())
    return repo


def release_policy(root: Path, repo: str) -> str | None:
    """'tags' when the project's library says this repo is installed from release tags (base and hub by default)."""
    lib = read_json(root / ".agate/library.json")
    want = _norm_repo(repo)
    entries = list(lib.get("sources", []))
    if isinstance(lib.get("base"), dict):
        entries.append(lib["base"])
    for entry in entries:
        if entry.get("repo") and _norm_repo(entry["repo"]) == want and entry.get("releases") == "tags":
            return "tags"
    return None


def latest_tag(repo: str, include_pre: bool = False, timeout: float = 15.0) -> tuple[str, str] | None:
    """Latest semver release tag of a repo as (tag, commit), via `git ls-remote --tags` (nothing downloaded)."""
    source = repo if is_url(repo) else str(Path(repo).expanduser().resolve())
    out = subprocess.run(["git", "ls-remote", "--tags", source], capture_output=True, text=True, timeout=timeout,
                         check=True).stdout
    commits: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        name = parts[1][len("refs/tags/"):]
        peeled = name.endswith("^{}")
        name = name[:-3] if peeled else name
        if peeled or name not in commits:
            commits[name] = parts[0]
    best = None
    for name, commit in commits.items():
        m = _SEMVER.match(name)
        if not m or (m.group(4) and not include_pre):
            continue
        key = (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1)
        if best is None or key > best[0]:
            best = (key, name, commit)
    return (best[1], best[2]) if best else None


def release_ref(root: Path, repo: str) -> str | None:
    """The tag to install from when the repo follows releases; None for pinned/plain sources.

    Raises RuntimeError when the repo follows releases but has no release tag yet (never falls back to the branch).
    """
    if release_policy(root, repo) != "tags":
        return None
    found = latest_tag(repo)
    if not found:
        raise RuntimeError(f"{repo} has no release tag (vX.Y.Z) yet; Agate never installs from the branch tip.")
    return found[0]


def consent_line(name: str, source: str, license_: str, scripts: list[str]) -> str:
    first = ", ".join(scripts[:3]) + ("…" if len(scripts) > 3 else "")
    return (f"{name} from {source} ({license_ or 'license unknown'}) includes {len(scripts)} scripts ({first}) "
            f"→ ask the person: install? then rerun with --yes")


def folder_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_dir() or rel.startswith(".git/") or "/__pycache__/" in f"/{rel}" or rel.endswith(".pyc"):
            continue
        h.update(f"{rel}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def today() -> str:
    return _dt.date.today().isoformat()


# ---------------------------------------------------------------- the lock

def load_lock(root: Path) -> dict:
    """Read `.agate/lock.json`; the first time, import older records (skills.lock.json, manifest `source`)."""
    path = root / LOCK
    if path.is_file():
        data = read_json(path)
        data.setdefault("packages", {})
        return data
    data = {"version": 2, "packages": {}}
    imported = []
    old = root / OLD_SKILLS_LOCK
    if old.is_file():
        for name, entry in read_json(old).get("skills", {}).items():
            data["packages"][name] = {**entry, "kind": "skill"}
            imported.append(name)
    manifests = [(root / ".agate/manifest.json", "base")]
    exp_dir = root / ".agate/expansions"
    if exp_dir.is_dir():
        manifests += [(p, "extension") for p in sorted(exp_dir.glob("*.json"))]
    for mpath, kind in manifests:
        manifest = read_json(mpath)
        source = manifest.get("source")
        if manifest and source:
            name = manifest.get("name", mpath.stem)
            data["packages"][name] = {"kind": kind, "name": name, "repo": source.get("repo"),
                                      "path": source.get("path", ""), "ref": source.get("commit"),
                                      "version": manifest.get("version"), "installed": today()}
            imported.append(name)
    if imported:
        save_lock(root, data)
        removed = old.is_file()
        if removed:
            old.unlink()
        MIGRATION_NOTES.append(f"Migrated {', '.join(imported)} into {LOCK.as_posix()} (one lock for every package)"
                               + (f"; removed {OLD_SKILLS_LOCK.as_posix()}." if removed else "."))
    return data


def save_lock(root: Path, data: dict) -> None:
    path = root / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "packages": dict(sorted(data.get("packages", {}).items()))}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record(root: Path, name: str, kind: str, source: dict, version: str | None) -> None:
    """Record (or refresh) a base/extension package after a sync."""
    data = load_lock(root)
    entry = {"kind": kind, "name": name, "repo": source.get("repo"), "path": source.get("path", ""),
             "ref": source.get("commit"), "version": version, "installed": today()}
    if source.get("tag"):
        entry["tag"] = source["tag"]
    data["packages"][name] = entry
    save_lock(root, data)


# ---------------------------------------------------------------- check (all packages)

def skill_rows(root: Path) -> list[dict]:
    import skills_sync as ss  # noqa: PLC0415
    rows = []
    proj = ss.Project(root)
    for name, entry in sorted(proj.lock["skills"].items()):
        row = {"kind": "skill", "name": name, "installed": entry.get("ref", "?"), "available": None,
               "source": f"{entry.get('source')}/{name}", "status": "unknown"}
        try:
            src = proj.source(entry["source"])
            ref, tag = ss.effective_ref(proj, src, None)
            items, commit = proj.catalog(src, ref, refresh=True)
            if tag:
                row["installed"], row["available"] = entry.get("tag") or entry.get("ref", "?"), tag
            row["available"] = row["available"] or commit
            if name not in items:
                row["status"] = "missing upstream"
            elif folder_hash(items[name]["dir"]) != entry.get("sha256"):
                row["status"] = "update available"
            else:
                row["status"] = "up to date"
        except Exception as exc:  # noqa: BLE001  (network, git, unknown source: report, don't fail)
            row["status"] = f"unreachable ({exc.__class__.__name__})"
        rows.append(row)
    return rows


def check_rows(root: Path, base_from: str | None = None) -> list[dict]:
    import sync  # noqa: PLC0415
    load_lock(root)
    return sync.check(root, base_from) + skill_rows(root) + app_rows(root)


def has_update(row: dict) -> bool:
    return row["status"].startswith(("update", "new commits"))


# ---------------------------------------------------------------- update checks for `start` (cheap, scheduled)

STATE = Path("memory/local/state.json")
DEFAULT_SCHEDULE = "1h, 2h, 1d"
DEFAULT_NOTICE_HOURS = 24


def parse_duration(text: str) -> _dt.timedelta:
    """'30m', '12h', '1d', '7d', '1w' → timedelta."""
    import re  # noqa: PLC0415
    m = re.fullmatch(r"\s*(\d+)\s*([mhdw])\s*", str(text).lower())
    if not m:
        raise ValueError(f"'{text}' is not a duration (use 30m, 12h, 1d, 7d, 1w).")
    n, unit = int(m.group(1)), m.group(2)
    return {"m": _dt.timedelta(minutes=n), "h": _dt.timedelta(hours=n), "d": _dt.timedelta(days=n),
            "w": _dt.timedelta(weeks=n)}[unit]


def _settings(root: Path) -> tuple[list[_dt.timedelta], _dt.timedelta]:
    try:
        import config  # noqa: PLC0415
        cfg = config.read_config(root)
    except Exception:  # noqa: BLE001
        cfg = {}
    try:
        steps = [parse_duration(s) for s in str(cfg.get("update_check_schedule") or DEFAULT_SCHEDULE).split(",")
                 if s.strip()]
    except ValueError:
        steps = [parse_duration(s) for s in DEFAULT_SCHEDULE.split(",")]
    hours = cfg.get("update_notice_hours")
    notice = _dt.timedelta(hours=hours if isinstance(hours, (int, float)) and hours > 0 else DEFAULT_NOTICE_HOURS)
    return steps or [_dt.timedelta(hours=1)], notice


def _now() -> _dt.datetime:
    import os  # noqa: PLC0415
    fixed = os.environ.get("AGATE_NOW")
    return _dt.datetime.fromisoformat(fixed) if fixed else _dt.datetime.now()


def read_state(root: Path) -> dict:
    try:
        return read_json(root / STATE)
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(root: Path, state: dict) -> None:
    path = root / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def lock_fingerprint(root: Path) -> str:
    pk = load_lock(root)["packages"]
    manifest = read_json(root / ".agate/manifest.json")
    rows = sorted(f"{n}:{e.get('kind')}:{e.get('ref')}:{e.get('version')}:{e.get('sha256')}" for n, e in pk.items())
    rows.append(f"base-manifest:{manifest.get('version')}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]


def watched_repos(root: Path) -> list[str]:
    import sync  # noqa: PLC0415
    repos = {e["repo"] for e in load_lock(root)["packages"].values() if e.get("repo")}
    if (root / ".agate/manifest.json").is_file() and not any(
            e.get("kind") == "base" for e in load_lock(root)["packages"].values()):
        repos.add(sync.DEFAULT_BASE_REPO)
    return sorted(repos)


def ls_remote(repo: str, timeout: float = 10.0) -> str:
    """Head commit of a repo (path or URL) without downloading anything."""
    out = subprocess.run(["git", "ls-remote", repo, "HEAD"], capture_output=True, text=True, timeout=timeout,
                         check=True)
    head = out.stdout.split()
    if not head:
        raise ValueError("empty ls-remote")
    return head[0]


def _label_updates(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        if r["kind"] == "base":
            out.insert(0, f"base:{r.get('available') or '?'}")
        else:
            out.append(r["name"])
    return out


def update_notice(root: Path, offline: bool = False) -> str | None:
    """Scheduled, cheap update check for `start`. Returns at most one notice line, or None.

    Checks only when due (first start of the day, or after the current backoff step), using `git ls-remote`; the
    precise (downloading) check runs only when a watched repo's head moved. Offline/errors never advance the step.
    """
    now = _now()
    steps, notice_every = _settings(root)
    state = read_state(root)
    st = state.setdefault("updates", {})
    fp = lock_fingerprint(root)
    if st.get("fingerprint") != fp:  # something was installed, updated or pulled: start over
        st.update({"fingerprint": fp, "step": 0, "pending": [], "heads": {}})
    last = st.get("last_check")
    last_dt = _dt.datetime.fromisoformat(last) if last else None
    step = min(int(st.get("step", 0)), len(steps) - 1)
    due = last_dt is None or last_dt.date() != now.date() or now - last_dt >= steps[step]
    if due and not offline:
        heads, failed = {}, 0
        repos = watched_repos(root)
        for repo in repos:
            try:
                # Watching the branch head is enough: when it moves, the precise check compares release tags.
                heads[repo] = ls_remote(repo)
            except (OSError, subprocess.SubprocessError, ValueError):
                failed += 1
        if heads or not repos:
            moved = [r for r, h in heads.items() if st.get("heads", {}).get(r) != h]
            st.setdefault("heads", {}).update(heads)
            if moved:
                try:
                    st["pending"] = _label_updates([r for r in check_rows(root) if has_update(r)])
                except Exception:  # noqa: BLE001  (a failed precise check must never break start)
                    st["heads"] = {r: h for r, h in st["heads"].items() if r not in moved}
            st["step"] = 0 if st.get("pending") else min(step + 1, len(steps) - 1)
            st["last_check"] = now.isoformat(timespec="seconds")
    line = None
    snooze_at = st.get("snooze_until")
    snoozed = bool(snooze_at) and now < _dt.datetime.fromisoformat(snooze_at)
    last_notice = st.get("last_notice")
    if st.get("pending") and not snoozed and (
            not last_notice or now - _dt.datetime.fromisoformat(last_notice) >= notice_every):
        items = st["pending"]
        base = next((p for p in items if p.startswith("base:")), None)
        others = [p for p in items if not p.startswith("base:")]
        if base:
            head = f"Agate {base.split(':', 1)[1]} available" + (f" (base + {len(others)})" if others else "")
        else:
            head = "Updates available: " + ", ".join(others[:4]) + (f" (+{len(others) - 4})" if len(others) > 4 else "")
        line = (head + " → offer it to the person; apply only with their ok "
                "(`python3 .agate/agate.py update`; `update --snooze 7d` if they say later).")
        st["last_notice"] = now.isoformat(timespec="seconds")
    write_state(root, state)
    return line


def snooze(root: Path, duration: str) -> _dt.datetime:
    until = _now() + parse_duration(duration)
    state = read_state(root)
    state.setdefault("updates", {})["snooze_until"] = until.isoformat(timespec="seconds")
    write_state(root, state)
    return until


def mark_applied(root: Path) -> None:
    state = read_state(root)
    st = state.setdefault("updates", {})
    st.update({"pending": [], "step": 0, "heads": {}, "fingerprint": lock_fingerprint(root)})
    write_state(root, state)


# ---------------------------------------------------------------- apps (hub apps/, on demand only)

APPS_DIR = Path(".agate/apps")


def hub_apps_path(root: Path) -> str:
    import sync  # noqa: PLC0415
    for source in sync.read_json(root / sync.LIBRARY).get("sources", []):
        if source.get("id") == "agate":
            return (source.get("apps") or "apps/").strip("/")
    return "apps"


def install_app(root: Path, name: str, hub: str | None = None, ref_label: str = "", yes: bool = False) -> int:
    import sync  # noqa: PLC0415
    repo = hub or sync.hub_repo(root)
    sub = f"{hub_apps_path(root)}/{name}"
    tmp = Path(tempfile.mkdtemp(prefix="agate-app-"))
    try:
        try:
            tag = release_ref(root, repo)
            folder, commit = fetch(repo, sub, tmp, tag)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"Error: could not fetch app '{name}' from {repo} ({exc.__class__.__name__}).", file=sys.stderr)
            return 1
        if not folder.is_dir():
            print(f"Error: the hub has no app '{name}' ({repo}#{sub}).", file=sys.stderr)
            return 1
        scripts = script_files(folder)
        if scripts and not yes:
            meta0 = read_json(folder / "app.json") or read_json(folder / "agate.json")
            print(consent_line(f"app:{name}", f"{repo}{'@' + tag if tag else ''}", meta0.get("license", "own"),
                               scripts))
            return 3
        dest = root / APPS_DIR / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        meta = read_json(dest / "app.json") or read_json(dest / "agate.json")
        data = load_lock(root)
        data["packages"][f"app:{name}"] = {"kind": "app", "name": name, "repo": repo, "path": sub, "ref": commit,
                                           "version": meta.get("version"), "sha256": folder_hash(dest),
                                           "installed": today()}
        if tag:
            data["packages"][f"app:{name}"]["tag"] = tag
        save_lock(root, data)
        print(f"Installed app '{name}' ({meta.get('version') or '?'}{', ' + tag if tag else ''}) in "
              f"{(APPS_DIR / name).as_posix()}.")
        readme = next((p for p in ("README.md", "APP.md") if (dest / p).is_file()), None)
        if readme:
            print(f"  How to open it: {(APPS_DIR / name / readme).as_posix()}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove_app(root: Path, name: str) -> int:
    data = load_lock(root)
    key = f"app:{name}"
    dest = root / APPS_DIR / name
    if key not in data["packages"] and not dest.exists():
        print(f"App '{name}' is not installed.", file=sys.stderr)
        return 1
    data["packages"].pop(key, None)
    save_lock(root, data)
    if dest.exists():
        shutil.rmtree(dest)
    print(f"Removed app '{name}'.")
    return 0


def app_rows(root: Path) -> list[dict]:
    rows = []
    for key, e in sorted(load_lock(root)["packages"].items()):
        if e.get("kind") != "app":
            continue
        row = {"kind": "app", "name": e["name"], "installed": e.get("version") or e.get("ref"), "available": None,
               "source": f"{e.get('repo')}#{e.get('path')}", "status": "unknown"}
        tmp = Path(tempfile.mkdtemp(prefix="agate-appcheck-"))
        try:
            tag = release_ref(root, e["repo"])
            folder, commit = fetch(e["repo"], e["path"], tmp, tag)
            row["available"] = tag or (read_json(folder / "app.json") or read_json(folder / "agate.json")).get(
                "version") or commit
            if tag:
                row["installed"] = e.get("tag") or row["installed"]
            row["status"] = ("missing upstream" if not folder.is_dir() else
                             "up to date" if folder_hash(folder) == e.get("sha256") else "update available")
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError) as exc:
            row["status"] = f"unreachable ({exc.__class__.__name__})"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        rows.append(row)
    return rows


def app_changed_scripts(root: Path, name: str) -> list[str]:
    e = load_lock(root)["packages"].get(f"app:{name}", {})
    tmp = Path(tempfile.mkdtemp(prefix="agate-appdiff-"))
    try:
        folder, _ = fetch(e["repo"], e["path"], tmp, release_ref(root, e["repo"]))
        return changed_scripts(root / APPS_DIR / name, folder)
    except (OSError, subprocess.CalledProcessError, RuntimeError, KeyError):
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def print_rows(rows: list[dict]) -> None:
    if not rows:
        print("Nothing installed to check.")
        return
    print(f"{'PACKAGE':<22} {'KIND':<10} {'INSTALLED':<12} {'AVAILABLE':<12} STATUS")
    for r in rows:
        name = "agate" if r["kind"] == "base" else r["name"]
        print(f"{name:<22} {r['kind']:<10} {str(r['installed'] or '?')[:12]:<12} "
              f"{str(r['available'] or '?')[:12]:<12} {r['status']}")
    if any(has_update(r) for r in rows):
        print("To update: python3 .agate/agate.py update (shows what changes), then with --yes.")


# ---------------------------------------------------------------- commands

def _root(a) -> Path:
    return Path(a.root).resolve()


def cmd_check(a) -> int:
    print_rows(check_rows(_root(a), a.source))
    return 0


def _source_for(root: Path, row: dict) -> str:
    import sync  # noqa: PLC0415
    entry = load_lock(root)["packages"].get(row["name"] if row["kind"] != "base" else "agate", {})
    if row["kind"] == "base":
        repo = entry.get("repo") or sync.DEFAULT_BASE_REPO
        return repo + (f"#{entry['path']}" if entry.get("path") else "")
    repo = entry.get("repo") or sync.hub_repo(root)
    sub = entry.get("path") or f"{sync.hub_extensions_path(root)}/{row['name']}"
    return f"{repo}#{sub}"


def cmd_update(a) -> int:
    import skills_sync as ss  # noqa: PLC0415
    import sync  # noqa: PLC0415
    root = _root(a)
    if getattr(a, "snooze", None):
        try:
            until = snooze(root, a.snooze)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        print(f"Update notices snoozed until {until:%Y-%m-%d %H:%M}.")
        return 0
    if a.source:
        code = sync.run_sync(root, a.source, dry_run=not a.yes)
        if a.yes and code == 0:
            mark_applied(root)
        return code
    rows = check_rows(root)
    wanted = set(a.names or [])
    code = 0
    for row in rows:
        label = "agate" if row["kind"] == "base" else row["name"]
        if wanted and label not in wanted and row["name"] not in wanted:
            continue
        if not wanted and not has_update(row):
            continue
        if row["kind"] in ("base", "extension"):
            print(f"== {label} ({row['kind']}): {row['installed']} → {row['available'] or '?'}")
            code = max(code, sync.run_sync(root, _source_for(root, row), dry_run=not a.yes))
        elif row["kind"] == "app":
            print(f"== app {label}: {row['installed']} → {row['available'] or '?'}")
            changed = app_changed_scripts(root, row["name"])
            if changed:
                print("  scripts changed: " + ", ".join(changed))
            if a.yes:
                entry = load_lock(root)["packages"].get(f"app:{row['name']}", {})
                code = max(code, install_app(root, row["name"], entry.get("repo"), yes=True))
        else:
            ns = argparse.Namespace(name=row["name"], ref=getattr(a, "ref", None), yes=a.yes, force=a.force)
            code = max(code, ss.cmd_update(ss.Project(root), ns))
    if a.yes and code == 0:
        mark_applied(root)
    if not a.yes and code == 0 and any(has_update(r) for r in rows):
        print("Nothing applied. Run again with --yes (after the person's ok).")
    if not any(has_update(r) for r in rows) and not wanted:
        print("Everything is up to date.")
    return code


def _is_extension(root: Path, name: str) -> str | None:
    """Return the hub source string if `name` is an extension in the hub, else None (offline: None)."""
    import sync  # noqa: PLC0415
    source = f"{sync.hub_repo(root)}#{sync.hub_extensions_path(root)}/{name}"
    tmp = Path(tempfile.mkdtemp(prefix="agate-add-"))
    try:
        repo, sub = sync.split_source(source)
        folder, _ = fetch(repo, sub, tmp, release_ref(root, repo))
        return source if (folder / ".agate/expansions").is_dir() else None
    except (OSError, subprocess.CalledProcessError, RuntimeError):
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_add(a) -> int:
    import skills_sync as ss  # noqa: PLC0415
    import sync  # noqa: PLC0415
    root = _root(a)
    target = a.target
    if target.startswith("app:"):
        return install_app(root, target[4:], a.hub, yes=a.yes)
    if target.startswith("ext:"):
        name = target[4:]
        return sync.run_sync(root, f"{a.hub or sync.hub_repo(root)}#{sync.hub_extensions_path(root)}/{name}", False,
                             consent=a.yes)
    if not target.startswith("pack:") and "/" not in target:
        if a.hub:
            return sync.run_sync(root, f"{a.hub}#{sync.hub_extensions_path(root)}/{target}", False, consent=a.yes)
        source = _is_extension(root, target)
        if source:
            return sync.run_sync(root, source, False, consent=a.yes)
    try:
        return ss.cmd_add(ss.Project(root), argparse.Namespace(target=target, yes=a.yes, force=a.force))
    except ss.UserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _skills_cmd(fn_name: str):
    def run(a) -> int:
        import skills_sync as ss  # noqa: PLC0415
        try:
            return getattr(ss, fn_name)(ss.Project(_root(a)), a)
        except ss.UserError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return run


def cmd_remove(a) -> int:
    if a.name.startswith("app:"):
        return remove_app(_root(a), a.name[4:])
    return _skills_cmd("cmd_remove")(a)


def cmd_list(a) -> int:
    root = _root(a)
    data = load_lock(root)["packages"]
    for name, e in sorted(data.items()):
        if e.get("kind") in ("base", "extension", "app"):
            print(f"  {name:<22} {e['kind']:<11} {e.get('version') or '?'} · {e.get('repo') or ''}"
                  + (f"#{e['path']}" if e.get("path") else ""))
    return _skills_cmd("cmd_list")(a)


def register(sub, root: Path) -> None:
    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(func=fn)
        return p

    p = add("check", cmd_check, "list available updates for the base, extensions and skills (changes nothing)")
    p.add_argument("--from", dest="source", help="base path or URL to compare with")
    p = add("update", cmd_update, "show updates for every package; apply them with --yes")
    p.add_argument("names", nargs="*", help="only these packages (default: all with updates)")
    p.add_argument("--yes", action="store_true", help="apply (with the person's ok)")
    p.add_argument("--force", action="store_true", help="also overwrite manual edits in library skills")
    p.add_argument("--from", dest="source", help="sync from this base/extension path or URL (#sub-path allowed)")
    p.add_argument("--snooze", metavar="DURATION", help="silence update notices for 12h, 1d, 7d… (person said later)")
    p.add_argument("--ref", help="move a pinned skill source to this commit (shows the diff first)")
    p = add("add", cmd_add, "install an extension (name or ext:name), a skill (source/skill, skill, pack:name) or "
                            "an app (app:name, on demand)")
    p.add_argument("target")
    p.add_argument("--hub", help="hub path or URL for extensions/apps (default: source 'agate' in .agate/library.json)")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--force", action="store_true")
    p = add("remove", cmd_remove, "remove a library skill, or an app (app:name)")
    p.add_argument("name")
    p.add_argument("--force", action="store_true")
    p = add("search", _skills_cmd("cmd_search"), "search skills in the library sources")
    p.add_argument("text")
    p.add_argument("--source")
    p.add_argument("--refresh", action="store_true")
    add("list", cmd_list, "installed packages")
    add("verify", _skills_cmd("cmd_verify"), "detect manual edits in library skills")
    p = add("doctor", _skills_cmd("cmd_doctor"), "what each skill needs installed")
    p.add_argument("name", nargs="?")
    p = add("sources", _skills_cmd("cmd_sources"), "list library sources and packs, or add a source")
    p.add_argument("--add", nargs=2, metavar=("ID", "REPO"))
    p.add_argument("--path", default="skills/")
    p.add_argument("--ref")
    p.add_argument("--trusted", action="store_true")
