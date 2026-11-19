#!/usr/bin/env python3
"""Agate skills library: search, install, update and check skills from other sources.

Usage (from the project root):
    python3 .agate/agate.py sources [--add ID REPO [--path skills/] [--ref REF] [--trusted]]
    python3 .agate/agate.py search TEXT [--source ID] [--refresh]
    python3 .agate/agate.py add SOURCE/SKILL | SKILL | pack:NAME [--yes] [--force]
    python3 .agate/agate.py remove SKILL [--force]
    python3 .agate/agate.py update [SKILL] [--ref REF] [--yes] [--force]
    python3 .agate/agate.py list
    python3 .agate/agate.py verify
    python3 .agate/agate.py doctor [SKILL]

Skills are COPIED into .agents/skills/<name>/ (and committed) and recorded in .agate/lock.json
with their source, exact commit, license and a fingerprint (sha256) of the folder.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LIBRARY = Path(".agate/library.json")
LOCK = Path(".agate/lock.json")  # one lock for every package (base, extensions, skills); see packages.py
MANIFEST = Path(".agate/manifest.json")
SKILLS_DIR = Path(".agents/skills")
CACHE_DIR = Path("memory/local/.cache/skills")

EXIT_OK, EXIT_ERROR, EXIT_NEEDS_YES = 0, 1, 3


# ---------- helpers ----------

class UserError(Exception):
    """Error shown to the person without a traceback."""


def find_root(start: Path) -> Path:
    for d in [start, *start.parents]:
        if (d / LIBRARY).is_file() or (d / MANIFEST).is_file():
            return d
    for d in [start, *start.parents]:
        if (d / ".git").exists():
            return d
    return start


def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise UserError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def folder_files(folder: Path) -> dict[str, str]:
    """Relative path → sha256 of each file (without .git or __pycache__)."""
    out: dict[str, str] = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_dir() or rel.startswith(".git/") or "/__pycache__/" in f"/{rel}" or rel.endswith(".pyc"):
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def folder_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for rel, digest in folder_files(folder).items():
        h.update(f"{rel}\0{digest}\n".encode())
    return h.hexdigest()


def parse_frontmatter(text: str) -> dict[str, str]:
    """Read name/description from a SKILL.md YAML frontmatter (including `>` and `|` block values)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    lines = text[3:end].splitlines()
    data: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block = []
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            value = " ".join(b for b in block if b)
        else:
            i += 1
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].replace('\\"', '"')
        data[key] = value
    return data


def today() -> str:
    return _dt.date.today().isoformat()


# ---------- project ----------

class Project:
    def __init__(self, root: Path):
        self.root = root
        self.library = read_json(root / LIBRARY, {"sources": [], "packs": {}, "exclude": [], "requires": {}})
        import packages  # noqa: PLC0415  (shared lock layer)
        self._packages = packages
        data = packages.load_lock(root)
        self.lock = {"skills": {n: e for n, e in data["packages"].items() if e.get("kind") == "skill"}}

    # sources
    def sources(self) -> list[dict]:
        return list(self.library.get("sources", []))

    def source(self, sid: str) -> dict:
        for s in self.sources():
            if s["id"] == sid:
                return s
        raise UserError(f"Unknown source '{sid}'. Sources: {', '.join(s['id'] for s in self.sources()) or 'none'}.")

    def save_lock(self) -> None:
        data = self._packages.load_lock(self.root)
        data["packages"] = {n: e for n, e in data["packages"].items() if e.get("kind") != "skill"}
        for name, entry in self.lock["skills"].items():
            data["packages"][name] = {**entry, "kind": "skill"}
        self._packages.save_lock(self.root, data)

    def save_library(self) -> None:
        write_json(self.root / LIBRARY, self.library)

    # base skills (never touched here)
    def base_owned(self) -> set[str]:
        manifest = read_json(self.root / MANIFEST, {})
        names = set()
        for entry in manifest.get("owned", []):
            m = re.match(r"^\.agents/skills/([^/]+)/?$", entry)
            if m:
                names.add(m.group(1))
        return names

    def installed_dirs(self) -> list[str]:
        d = self.root / SKILLS_DIR
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())

    # fetching a source
    def checkout(self, src: dict, ref: str | None, refresh: bool = False) -> tuple[Path, str]:
        """Put the source in the cache (memory/local/, outside git) and return (skills folder, commit)."""
        repo = src["repo"]
        local = Path(repo).expanduser()
        if not local.is_absolute():
            local = self.root / local
        if local.is_dir() and not (local / ".git").exists():
            return local / src.get("path", ""), "local"
        if local.is_dir():
            repo = str(local)
        key = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{src['id']}@{ref or 'HEAD'}")
        dest = self.root / CACHE_DIR / key
        if dest.is_dir() and refresh:
            shutil.rmtree(dest)
        if not dest.is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if ref:
                git("clone", "--quiet", "--filter=blob:none", "--no-checkout", repo, str(dest))
                git("checkout", "--quiet", ref, cwd=dest)
            else:
                git("clone", "--quiet", "--depth", "1", repo, str(dest))
        commit = git("rev-parse", "--short=7", "HEAD", cwd=dest)
        return dest / src.get("path", ""), commit

    def catalog(self, src: dict, ref: str | None = None, refresh: bool = False) -> tuple[dict[str, dict], str]:
        base, commit = self.checkout(src, ref, refresh)
        items: dict[str, dict] = {}
        if base.is_dir():
            for sk in sorted(base.iterdir()):
                f = sk / "SKILL.md"
                if f.is_file():
                    fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
                    items[sk.name] = {"name": sk.name, "description": fm.get("description", ""), "dir": sk}
        return items, commit

    def excluded(self, key: str) -> bool:
        return key in self.library.get("exclude", [])


# ---------- commands ----------

def cmd_sources(p: Project, a) -> int:
    if a.add:
        sid, repo = a.add
        if any(s["id"] == sid for s in p.sources()):
            raise UserError(f"A source '{sid}' already exists.")
        entry = {"id": sid, "repo": repo, "path": a.path, "trust": "trusted" if a.trusted else "untrusted"}
        if a.ref:
            entry["ref"] = a.ref
        p.library.setdefault("sources", []).append(entry)
        p.save_library()
        print(f"Source '{sid}' added ({entry['trust']}). Commit .agate/library.json to share it.")
        return EXIT_OK
    print("Sources (in order of preference):")
    for s in p.sources():
        extra = f" · ref {s['ref']}" if s.get("ref") else ""
        print(f"  {s['id']:<12} {s.get('trust', 'untrusted'):<9} {s.get('license', '?'):<11} {s['repo']}{extra}")
    packs = p.library.get("packs", {})
    if packs:
        print("\nPacks:")
        for name, items in packs.items():
            print(f"  pack:{name:<12} {', '.join(items)}")
    return EXIT_OK


def cmd_search(p: Project, a) -> int:
    words = [w.lower() for w in a.text.split()]
    found = 0
    installed = set(p.lock["skills"]) | set(p.installed_dirs())
    for src in p.sources():
        if a.source and src["id"] != a.source:
            continue
        try:
            items, commit = p.catalog(src, src.get("ref"), a.refresh)
        except UserError as e:
            print(f"  (could not read source '{src['id']}': {e})")
            continue
        for name, it in items.items():
            hay = f"{name} {it['description']}".lower()
            if all(w in hay for w in words):
                key = f"{src['id']}/{name}"
                tags = []
                if name in installed:
                    tags.append("installed")
                if p.excluded(key):
                    tags.append("not suggested")
                tag = f" [{', '.join(tags)}]" if tags else ""
                desc = it["description"]
                desc = desc if len(desc) <= 140 else desc[:137] + "…"
                print(f"{key}@{commit}{tag}\n    {desc}")
                found += 1
    if not found:
        print(f"No skills found for '{a.text}'. Try other words or add a source with `sources --add`.")
    return EXIT_OK


def resolve_targets(p: Project, target: str) -> list[tuple[dict, str]]:
    if target.startswith("pack:"):
        name = target[5:]
        items = p.library.get("packs", {}).get(name)
        if not items:
            raise UserError(f"No pack named '{name}'. Packs: {', '.join(p.library.get('packs', {})) or 'none'}.")
        out = []
        for item in items:
            out.extend(resolve_targets(p, item))
        return out
    if "/" in target:
        sid, name = target.split("/", 1)
        return [(p.source(sid), name)]
    for src in p.sources():
        try:
            items, _ = p.catalog(src, src.get("ref"))
        except UserError:
            continue
        if target in items:
            return [(src, target)]
    raise UserError(f"Skill '{target}' not found in any source.")


def describe_for_review(folder: Path) -> str:
    files = folder_files(folder)
    skill = (folder / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    head = "\n".join(skill.splitlines()[:60])
    listing = "\n".join(f"  - {f}" for f in files)
    return f"--- SKILL.md (first 60 lines) ---\n{head}\n--- Files ({len(files)}) ---\n{listing}"


def install_one(p: Project, src: dict, name: str, a, ref: str | None = None) -> int:
    key = f"{src['id']}/{name}"
    dest = p.root / SKILLS_DIR / name
    if name in p.base_owned():
        raise UserError(f"'{name}' is an Agate base skill: it is updated with `agate.py update`, not here.")
    locked = p.lock["skills"].get(name)
    if dest.exists():
        if locked and locked.get("source") == src["id"]:
            print(f"'{name}' is already installed ({locked['source']}@{locked['ref']}). To pull changes: update {name}.")
            return EXIT_OK
        if not a.force:
            raise UserError(f".agents/skills/{name} already exists and does not come from '{src['id']}'. "
                        f"Not overwriting it: use --force only if you want to replace it.")
    items, commit = p.catalog(src, ref if ref is not None else src.get("ref"))
    if name not in items:
        raise UserError(f"Source '{src['id']}' has no skill '{name}'.")
    origin_dir = items[name]["dir"]
    trusted = src.get("trust") == "trusted"
    if p.excluded(key):
        print(f"Note: '{key}' is not suggested for Agate (see library.json → exclude). Installing it anyway because you asked for it.")
    if not trusted and not a.yes:
        print(f"Source '{src['id']}' is not trusted. Review what '{name}' contains before installing it:\n")
        print(describe_for_review(origin_dir))
        print(f"\nIf it looks fine, run again with --yes: agate.py add {key} --yes")
        return EXIT_NEEDS_YES
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origin_dir, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    license_ = src.get("license") or detect_license(dest)
    p.lock["skills"][name] = {
        "kind": "skill",
        "name": name,
        "source": src["id"],
        "repo": src["repo"],
        "ref": commit,
        "path": f"{src.get('path', '').rstrip('/')}/{name}".lstrip("/"),
        "license": license_,
        "sha256": folder_hash(dest),
        "installed": today(),
    }
    p.save_lock()
    print(f"Installed '{name}' ({src['id']}@{commit}, {license_}) in .agents/skills/{name}.")
    print(f"  Read it now and follow it: .agents/skills/{name}/SKILL.md")
    print(f"  Suggested commit: skills: add {name} ({src['id']}@{commit})")
    missing = doctor_missing(p, key)
    if missing:
        print(f"  Missing dependencies: {', '.join(m['what'] for m in missing)}. Details: agate.py doctor {name}")
    return EXIT_OK


def detect_license(folder: Path) -> str:
    for cand in ("LICENSE.txt", "LICENSE", "LICENSE.md"):
        f = folder / cand
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace")[:2000]
            for pat, label in (("Apache License", "Apache-2.0"), ("MIT License", "MIT"), ("GNU GENERAL PUBLIC", "GPL")):
                if pat in text:
                    return label
            return "see " + cand
    return "unknown"


def cmd_add(p: Project, a) -> int:
    code = EXIT_OK
    for src, name in resolve_targets(p, a.target):
        code = max(code, install_one(p, src, name, a))
    return code


def cmd_remove(p: Project, a) -> int:
    name = a.name
    if name in p.base_owned():
        raise UserError(f"'{name}' is an Agate base skill: it cannot be removed from here.")
    dest = p.root / SKILLS_DIR / name
    if name not in p.lock["skills"] and not a.force:
        raise UserError(f"'{name}' did not come from the library (it is the project's own). Use --force if you really want to delete it.")
    if dest.exists():
        shutil.rmtree(dest)
    p.lock["skills"].pop(name, None)
    p.save_lock()
    print(f"Removed '{name}'. Suggested commit: skills: remove {name}")
    return EXIT_OK


def cmd_update(p: Project, a) -> int:
    names = [a.name] if a.name else sorted(p.lock["skills"])
    if not names:
        print("No library skills installed.")
        return EXIT_OK
    code = EXIT_OK
    for name in names:
        entry = p.lock["skills"].get(name)
        if not entry:
            raise UserError(f"'{name}' is not in .agate/lock.json.")
        src = p.source(entry["source"])
        items, commit = p.catalog(src, a.ref, refresh=True)
        if name not in items:
            print(f"'{name}': the source no longer has it. Leaving it as is.")
            continue
        dest = p.root / SKILLS_DIR / name
        local_files = folder_files(dest) if dest.is_dir() else {}
        new_files = folder_files(items[name]["dir"])
        edited = dest.is_dir() and folder_hash(dest) != entry["sha256"]
        if folder_hash(items[name]["dir"]) == entry["sha256"]:
            print(f"'{name}' is up to date ({entry['ref']}).")
            continue
        added = sorted(set(new_files) - set(local_files))
        removed = sorted(set(local_files) - set(new_files))
        changed = sorted(f for f in set(new_files) & set(local_files) if new_files[f] != local_files[f])
        print(f"'{name}': {entry['source']}@{entry['ref']} → {commit}")
        for label, group in (("added", added), ("removed", removed), ("changed", changed)):
            if group:
                print(f"  {label}: {', '.join(group)}")
        if edited:
            print("  Careful: the project copy has manual edits; updating would overwrite them.")
        if not a.yes or (edited and not a.force):
            hint = " --force" if edited else ""
            print(f"  To apply: agate.py update {name} --yes{hint}")
            code = EXIT_NEEDS_YES
            continue
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(items[name]["dir"], dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        entry.update(ref=commit, sha256=folder_hash(dest), installed=today())
        p.save_lock()
        print(f"  Updated. Suggested commit: skills: update {name} ({entry['source']}@{commit})")
    return code


def cmd_list(p: Project, a) -> int:
    base = p.base_owned()
    rows = []
    for name in p.installed_dirs():
        if name in base:
            rows.append((name, "base", ""))
        elif name in p.lock["skills"]:
            e = p.lock["skills"][name]
            rows.append((name, "library", f"{e['source']}@{e['ref']} · {e.get('license', '?')}"))
        else:
            rows.append((name, "own", ""))
    if not rows:
        print("No skills installed in .agents/skills/.")
    for name, kind, extra in rows:
        print(f"  {name:<22} {kind:<11} {extra}")
    return EXIT_OK


def cmd_verify(p: Project, a) -> int:
    problems = 0
    for name, entry in sorted(p.lock["skills"].items()):
        dest = p.root / SKILLS_DIR / name
        if not dest.is_dir():
            print(f"  MISSING     {name} (in the lock but not in .agents/skills/)")
            problems += 1
        elif folder_hash(dest) != entry["sha256"]:
            print(f"  MODIFIED    {name} (does not match {entry['source']}@{entry['ref']})")
            problems += 1
        else:
            print(f"  OK          {name}")
    if not p.lock["skills"]:
        print("No library skills to verify.")
    return EXIT_ERROR if problems else EXIT_OK


def doctor_missing(p: Project, key: str, include_optional: bool = False) -> list[dict]:
    req = p.library.get("requires", {}).get(key, {})
    missing = []
    for item in req.get("python", []):
        if item.get("optional") and not include_optional:
            continue
        if importlib.util.find_spec(item["import"]) is None:
            missing.append({"kind": "python", "what": item["pip"], "item": item})
    for item in req.get("bin", []):
        if item.get("optional") and not include_optional:
            continue
        if shutil.which(item["name"]) is None:
            missing.append({"kind": "bin", "what": item["name"], "item": item})
    node = shutil.which("node")
    for item in req.get("node", []):
        if item.get("optional") and not include_optional:
            continue
        ok = False
        if node:
            proc = subprocess.run([node, "-e", f"require.resolve({json.dumps(item['package'])})"],
                                  cwd=p.root, capture_output=True)
            ok = proc.returncode == 0
        if not ok:
            missing.append({"kind": "node", "what": f"{item['package']} (npm)", "item": item})
    return missing


def install_hint(m: dict) -> str:
    it = m["item"]
    if m["kind"] == "python":
        hint = f"pip install --user {it['pip']}"
        if it.get("after"):
            hint += f" && {it['after']}"
        return hint
    if m["kind"] == "node":
        return f"npm install {it['package']}"
    parts = []
    for mgr, label in (("apt", "Linux: sudo apt install"), ("brew", "Mac: brew install"), ("winget", "Windows: winget install")):
        if it.get(mgr):
            parts.append(f"{label} {it[mgr]}")
    heavy = " (heavy: ask before installing it)" if it.get("heavy") else ""
    return " · ".join(parts) + heavy


def cmd_doctor(p: Project, a) -> int:
    keys = []
    for name, e in sorted(p.lock["skills"].items()):
        if a.name and name != a.name:
            continue
        keys.append((name, f"{e['source']}/{name}"))
    if a.name and not keys:
        keys.append((a.name, a.name if "/" in a.name else next(
            (f"{s['id']}/{a.name}" for s in p.sources() if f"{s['id']}/{a.name}" in p.library.get("requires", {})),
            a.name)))
    total = 0
    for name, key in keys:
        missing = doctor_missing(p, key)
        optional = [m for m in doctor_missing(p, key, include_optional=True) if m not in missing]
        if not missing:
            print(f"  OK     {name}" + (f" (optional, not installed: {', '.join(m['what'] for m in optional)})" if optional else ""))
            continue
        total += len(missing)
        print(f"  MISSING {name}:")
        for m in missing:
            print(f"         - {m['what']}: {install_hint(m)}")
    if not keys:
        print("No library skills installed.")
    if total:
        print("\nThis tool installs nothing by itself: the agent installs lightweight things and asks before heavy ones (LibreOffice).")
    return EXIT_ERROR if total else EXIT_OK


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skills-sync.py", description="Agate skills library.")
    ap.add_argument("--root", type=Path, help="project root (by default, searched upwards)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sources", help="list sources and packs, or add a source")
    s.add_argument("--add", nargs=2, metavar=("ID", "REPO"))
    s.add_argument("--path", default="skills/")
    s.add_argument("--ref")
    s.add_argument("--trusted", action="store_true")
    s.set_defaults(fn=cmd_sources)

    s = sub.add_parser("search", help="search skills by name or description")
    s.add_argument("text")
    s.add_argument("--source")
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("add", help="install a skill (source/skill, skill or pack:name)")
    s.add_argument("target")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("remove", help="remove a library skill")
    s.add_argument("name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_remove)

    s = sub.add_parser("update", help="show and apply updates")
    s.add_argument("name", nargs="?")
    s.add_argument("--ref")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_update)

    sub.add_parser("list", help="installed skills").set_defaults(fn=cmd_list)
    sub.add_parser("verify", help="detect manual edits").set_defaults(fn=cmd_verify)

    s = sub.add_parser("doctor", help="check what each skill needs installed")
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    root = (a.root or find_root(Path.cwd())).resolve()
    try:
        return a.fn(Project(root), a)
    except UserError as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
