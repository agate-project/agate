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


def fetch(repo: str, sub: str, tmp: Path) -> tuple[Path, str | None]:
    """Make `repo` (path or URL) available locally. Returns (folder of the sub-path, commit).

    For URLs with a sub-path only that folder is downloaded (partial clone + sparse checkout); if the server or the
    local git doesn't support it, it falls back to a full shallow clone.
    """
    if not is_url(repo):
        root = Path(repo).expanduser().resolve()
        commit = git_commit(root) if (root / ".git").exists() else None
        return (root / sub if sub else root), commit
    dest = tmp / "src"

    def run(*args: str) -> None:
        subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    if sub:
        try:
            run("clone", "--quiet", "--filter=blob:none", "--no-checkout", "--depth", "1", repo, str(dest))
            run("-C", str(dest), "sparse-checkout", "set", sub)
            run("-C", str(dest), "checkout", "--quiet")
        except subprocess.CalledProcessError:
            shutil.rmtree(dest, ignore_errors=True)
            run("clone", "--quiet", "--depth", "1", repo, str(dest))
    else:
        run("clone", "--quiet", "--depth", "1", repo, str(dest))
    return (dest / sub if sub else dest), git_commit(dest)


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
    data["packages"][name] = {"kind": kind, "name": name, "repo": source.get("repo"), "path": source.get("path", ""),
                              "ref": source.get("commit"), "version": version, "installed": today()}
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
            items, commit = proj.catalog(src, None, refresh=True)
            row["available"] = commit
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
    return sync.check(root, base_from) + skill_rows(root)


def has_update(row: dict) -> bool:
    return row["status"].startswith(("update", "new commits"))


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
    if a.source:
        return sync.run_sync(root, a.source, dry_run=not a.yes)
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
        else:
            ns = argparse.Namespace(name=row["name"], ref=None, yes=a.yes, force=a.force)
            code = max(code, ss.cmd_update(ss.Project(root), ns))
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
        folder, _ = fetch(*sync.split_source(source), tmp)
        return source if (folder / ".agate/expansions").is_dir() else None
    except (OSError, subprocess.CalledProcessError):
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_add(a) -> int:
    import skills_sync as ss  # noqa: PLC0415
    import sync  # noqa: PLC0415
    root = _root(a)
    target = a.target
    if target.startswith("ext:"):
        name = target[4:]
        return sync.run_sync(root, f"{a.hub or sync.hub_repo(root)}#{sync.hub_extensions_path(root)}/{name}", False)
    if not target.startswith("pack:") and "/" not in target:
        if a.hub:
            return sync.run_sync(root, f"{a.hub}#{sync.hub_extensions_path(root)}/{target}", False)
        source = _is_extension(root, target)
        if source:
            return sync.run_sync(root, source, False)
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


def cmd_list(a) -> int:
    root = _root(a)
    data = load_lock(root)["packages"]
    for name, e in sorted(data.items()):
        if e.get("kind") in ("base", "extension"):
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
    p = add("add", cmd_add, "install an extension (name or ext:name) or a skill (source/skill, skill, pack:name)")
    p.add_argument("target")
    p.add_argument("--hub", help="hub path or URL for extensions (default: source 'agate' in .agate/library.json)")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--force", action="store_true")
    p = add("remove", _skills_cmd("cmd_remove"), "remove a library skill")
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
