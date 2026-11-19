#!/usr/bin/env python3
"""Bring in Agate base improvements (or install/update an expansion) without touching the project's own files.

Usage (from the project root):
    python3 .agate/agate.py update --from <path-or-url>[#<sub-path>] [--dry-run]
    python3 .agate/agate.py add <extension> [--hub <path-or-url>] [--dry-run]
    python3 .agate/agate.py check [--from <base-path-or-url>]

`--from` can be the base (ships `.agate/manifest.json`) or an expansion (ships `.agate/expansions/<name>.json`).
Extensions live in the hub (`agate-hub/extensions/<name>/`): point to them with `#extensions/<name>`, or use
`add <name>`, which takes the hub URL from `.agate/library.json` (source id `agate`). Only that folder is downloaded
(partial clone + sparse checkout).

`check` compares the installed base and each installed extension with their source (recorded at install time:
repo, sub-path, commit, version) and lists available updates without applying anything.

What it does, for each manifest found in the source:
- Copies the files and folders it declares as its own (`owned`): creates new ones and updates changed ones.
- In files with a block (`blocks`, e.g. AGENTS.md) it replaces only what sits between
  <!-- <marker>:begin --> and <!-- <marker>:end --> (marker `agate` for the base, `agate-<name>` for an expansion).
  In non-Markdown/HTML files (e.g. `.env.example`) the markers are lines `# <marker>:begin` / `# <marker>:end`.
  If an expansion doesn't have its block in the project yet, it is appended at the end of the file.
- Never deletes: if the source no longer ships a file, it only warns.
- Never touches memory/, documents/, artifacts/, archive/, .git/ or skills that don't belong to the source.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import packages as pkgs  # noqa: E402  (shared fetch + lock layer)

BASE_MANIFEST = Path(".agate/manifest.json")
EXPANSIONS_DIR = Path(".agate/expansions")
LIBRARY = Path(".agate/library.json")
DEFAULT_BASE_REPO = "https://github.com/agate-project/agate"
DEFAULT_HUB_REPO = "https://github.com/agate-project/agate-hub"
PROTECTED = ("memory/", "documents/", "artifacts/", "archive/", ".git/")


def is_url(value: str) -> bool:
    return "://" in value or value.startswith("git@")


def split_source(value: str) -> tuple[str, str]:
    """`<repo>#<sub-path>` → (repo, sub-path). No `#` → (value, "")."""
    if "#" in value:
        repo, sub = value.rsplit("#", 1)
        return repo, sub.strip("/")
    return value, ""


def git_commit(path: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def fetch(repo: str, sub: str, tmp: Path, ref: str | None = None) -> tuple[Path, str | None]:
    return pkgs.fetch(repo, sub, tmp, ref)


def hub_repo(project: Path) -> str:
    """Hub URL from the project's library (source id `agate`), or the default."""
    for source in read_json(project / LIBRARY).get("sources", []):
        if source.get("id") == "agate" and source.get("repo"):
            return source["repo"]
    return DEFAULT_HUB_REPO


def hub_extensions_path(project: Path) -> str:
    for source in read_json(project / LIBRARY).get("sources", []):
        if source.get("id") == "agate":
            return (source.get("extensions") or "extensions/").strip("/")
    return "extensions"


def read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


HTML_SUFFIXES = (".md", ".markdown", ".html", ".htm")


def markers(name: str, rel: str = "") -> tuple[str, str]:
    """Block markers by file type: HTML comments in .md/.html, `#` lines elsewhere (.env.example, .toml…)."""
    if not rel or rel.lower().endswith(HTML_SUFFIXES):
        return f"<!-- {name}:begin -->", f"<!-- {name}:end -->"
    return f"# {name}:begin", f"# {name}:end"


def normalize_blocks(manifest: dict, default_marker: str) -> dict[str, str]:
    """`blocks` can be a list (default marker) or a dict file → marker."""
    blocks = manifest.get("blocks", {})
    if isinstance(blocks, list):
        return {rel: default_marker for rel in blocks}
    return dict(blocks)


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", value or "0")[:3]) or (0,)


def requirement_ok(installed: str, requirement: str) -> bool:
    """Only understands ">=x.y.z" (what expansions use)."""
    match = re.match(r"\s*>=\s*(\S+)", requirement or "")
    if not match:
        return True
    return version_tuple(installed) >= version_tuple(match.group(1))


def protected(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in PROTECTED)


def covered(entry: str, owned: set[str]) -> bool:
    """True if `entry` is one of `owned` or sits inside an owned folder (e.g. `.agate/core/canvas/` in `.agate/core/`)."""
    entry = entry.replace("\\", "/")
    return any(entry == o or (o.endswith("/") and entry.startswith(o)) for o in owned)


def owned_files(root: Path, entry: str) -> list[str]:
    """Files (relative paths) covered by an `owned` entry inside `root`."""
    target = root / entry
    if entry.endswith("/"):
        if not target.is_dir():
            return []
        return sorted(
            p.relative_to(root).as_posix()
            for p in target.rglob("*")
            if (p.is_file() or p.is_symlink()) and "__pycache__" not in p.parts
        )
    return [entry] if (target.is_file() or target.is_symlink()) else []


def extract_block(text: str, marker: str, rel: str = "") -> str | None:
    begin, end = markers(marker, rel)
    try:
        b = text.index(begin)
        e = text.index(end, b) + len(end)
    except ValueError:
        return None
    return text[b:e]


def replace_block(project_text: str, upstream_text: str, marker: str = "agate", rel: str = "") -> str | None:
    """Return the project text with the block updated, or None if either side is missing the markers."""
    block = extract_block(upstream_text, marker, rel)
    current = extract_block(project_text, marker, rel)
    if block is None or current is None:
        return None
    start = project_text.index(current)
    return project_text[:start] + block + project_text[start + len(current):]


def find_packages(upstream: Path) -> list[dict]:
    """Manifests shipped by the source: the base and/or expansions."""
    packages = []
    base = read_json(upstream / BASE_MANIFEST)
    if base:
        packages.append({"kind": "base", "name": base.get("name", "agate"), "manifest": base,
                         "path": BASE_MANIFEST, "marker": "agate"})
    exp_dir = upstream / EXPANSIONS_DIR
    if exp_dir.is_dir():
        for path in sorted(exp_dir.glob("*.json")):
            manifest = read_json(path)
            name = manifest.get("name", path.stem)
            packages.append({"kind": "expansion", "name": name, "manifest": manifest,
                             "path": EXPANSIONS_DIR / path.name, "marker": f"agate-{name}"})
    return packages


def seed_files(project: Path, upstream: Path, manifest: dict, report: dict, dry_run: bool) -> None:
    """Project-layer files the base ships once (`seed`): created if missing, never overwritten.

    `.agate/library.json` is special: the project edits it, so only default sources/packs it lacks are merged in.
    """
    for rel in manifest.get("seed", []):
        src, dst = upstream / rel, project / rel
        if not src.is_file():
            continue
        if not dst.exists():
            report["created"].append(rel)
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            continue
        if rel == LIBRARY.as_posix():
            merged, added = merge_library(read_json(dst), read_json(src))
            if added:
                report["updated"].append(f"{rel} (+{', '.join(added)})")
                if not dry_run:
                    dst.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_library(local: dict, upstream: dict) -> tuple[dict, list[str]]:
    """Add upstream default sources/packs/requires the project lacks; never change or remove the project's."""
    merged, added = dict(local), []
    ids = {s.get("id") for s in merged.get("sources", [])}
    for source in upstream.get("sources", []):
        if source.get("id") not in ids:
            merged.setdefault("sources", []).append(source)
            added.append(f"source {source.get('id')}")
        elif source.get("releases"):
            mine = next(s for s in merged["sources"] if s.get("id") == source.get("id"))
            same_repo = pkgs._norm_repo(mine.get("repo", "")) == pkgs._norm_repo(source.get("repo", ""))
            if "releases" not in mine and same_repo:
                mine["releases"] = source["releases"]
                added.append(f"releases for source {source.get('id')}")
    if isinstance(upstream.get("base"), dict) and "base" not in merged:
        merged["base"] = upstream["base"]
        added.append("base releases policy")
    for key in ("packs", "requires"):
        for name, value in upstream.get(key, {}).items():
            if name not in merged.setdefault(key, {}):
                merged[key][name] = value
                added.append(f"{key[:-1]} {name}")
    return merged, added


def sync(project: Path, upstream: Path, dry_run: bool = False, source: dict | None = None) -> dict:
    """`source` ({"repo", "path", "commit"}) is recorded in each installed manifest, for `check`."""
    report = {"created": [], "updated": [], "unchanged": 0, "blocks": [], "warnings": [], "packages": []}
    packages = find_packages(upstream)
    if not packages:
        hint = ""
        if (upstream / "extensions").is_dir():
            names = ", ".join(sorted(d.name for d in (upstream / "extensions").iterdir() if d.is_dir()))
            hint = f" It looks like the hub: pick an extension with '#extensions/<name>' ({names})."
        raise SystemExit(f"Found neither {BASE_MANIFEST} nor {EXPANSIONS_DIR}/*.json in {upstream}. "
                         f"Is it the Agate base or an expansion?{hint}")

    local_base = read_json(project / BASE_MANIFEST)
    base_owned = set(local_base.get("owned", []))
    for pkg in packages:
        if pkg["kind"] == "base":
            base_owned |= set(pkg["manifest"].get("owned", []))

    def write(rel: str, src: Path) -> None:
        dst = project / rel
        if dst.is_symlink() or dst.exists():
            if src.is_symlink() and dst.is_symlink() and src.readlink() == dst.readlink():
                report["unchanged"] += 1
                return
            if not src.is_symlink() and dst.is_file() and not dst.is_symlink() and dst.read_bytes() == src.read_bytes():
                report["unchanged"] += 1
                return
            report["updated"].append(rel)
        else:
            report["created"].append(rel)
        if dry_run:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        if src.is_symlink():
            dst.symlink_to(src.readlink())
        else:
            shutil.copy2(src, dst)

    for pkg in packages:
        manifest, name, kind = pkg["manifest"], pkg["name"], pkg["kind"]
        local = read_json(project / pkg["path"])
        report["packages"].append({"name": name, "kind": kind,
                                   "from": local.get("version", "—"), "to": manifest.get("version", "?")})

        if kind == "expansion":
            requirement = manifest.get("requires", {}).get("agate", "")
            installed = local_base.get("version", "0")
            if requirement and not requirement_ok(installed, requirement):
                report["warnings"].append(
                    f"Expansion '{name}' requires Agate {requirement} and the project has {installed}: "
                    "update the base first.")

        # 1. Package files and folders.
        for entry in manifest.get("owned", []):
            if protected(entry):
                report["warnings"].append(f"'{name}' declares '{entry}', which belongs to the project: left untouched.")
                continue
            if kind == "expansion" and covered(entry, base_owned):
                report["warnings"].append(f"'{name}' declares '{entry}', which belongs to the base: left untouched.")
                continue
            up_files = owned_files(upstream, entry)
            for rel in up_files:
                write(rel, upstream / rel)
            for rel in owned_files(project, entry):
                if rel not in up_files:
                    report["warnings"].append(f"'{rel}' is no longer in '{name}'; kept (delete it if unused).")

        for entry in local.get("owned", []):
            if entry not in manifest.get("owned", []) and owned_files(project, entry):
                report["warnings"].append(f"'{entry}' is no longer part of '{name}'; it stays as the project's own.")

        # 2. Blocks inside shared files.
        for rel, marker in normalize_blocks(manifest, pkg["marker"]).items():
            src, dst = upstream / rel, project / rel
            if not src.is_file():
                continue
            upstream_text = src.read_text(encoding="utf-8")
            block = extract_block(upstream_text, marker, rel)
            if block is None:
                report["warnings"].append(f"'{rel}' from '{name}' has no {marker} block: skipped.")
                continue
            if not dst.is_file():
                if kind == "base":
                    write(rel, src)
                else:
                    report["blocks"].append(rel)
                    if not dry_run:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_text(block + "\n", encoding="utf-8")
                continue
            current = dst.read_text(encoding="utf-8")
            if extract_block(current, marker, rel) is None:
                if kind == "expansion":
                    new = current.rstrip("\n") + "\n\n" + block + "\n"
                else:
                    report["warnings"].append(f"'{rel}' has no {marker}:begin/end markers: not updated.")
                    continue
            else:
                new = replace_block(current, upstream_text, marker, rel)
            if new != current:
                report["blocks"].append(rel)
                if not dry_run:
                    dst.write_text(new, encoding="utf-8")
            else:
                report["unchanged"] += 1

        # 3. Seed files (base only): project-layer files created once, never overwritten.
        if kind == "base":
            seed_files(project, upstream, manifest, report, dry_run)

        # 4. Manifest (version and file list) and the lock entry (where it came from, for `check`).
        if not dry_run:
            (project / pkg["path"]).parent.mkdir(parents=True, exist_ok=True)
            installed = {k: v for k, v in manifest.items() if k != "source"}
            (project / pkg["path"]).write_text(json.dumps(installed, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
            pkgs.record(project, name, "base" if kind == "base" else "extension",
                            source or {}, manifest.get("version"))

    base_pkg = next((p for p in report["packages"] if p["kind"] == "base"), report["packages"][0])
    report["from_version"], report["to_version"] = base_pkg["from"], base_pkg["to"]
    return report


def print_report(report: dict, dry_run: bool) -> None:
    print("Dry run (nothing changed)" if dry_run else "Sync done")
    for pkg in report["packages"]:
        label = "Agate" if pkg["kind"] == "base" else f"Expansion {pkg['name']}"
        print(f"- {label}: {pkg['from']} → {pkg['to']}")
    for label, key in (("Created", "created"), ("Updated", "updated"), ("Blocks updated", "blocks")):
        items = report[key]
        if items:
            print(f"- {label} ({len(items)}):")
            for item in items:
                print(f"    {item}")
    print(f"- Unchanged: {report['unchanged']}")
    scripts = sorted({r for r in report["created"] + report["updated"] if pkgs.is_script_path(r)})
    if scripts:
        print("- scripts changed: " + ", ".join(scripts))
    for warning in report["warnings"]:
        print(f"! {warning}")


def check(project: Path, base_from: str | None = None) -> list[dict]:
    """Compare installed packages with their source. Returns one row per package; never changes anything."""
    rows: list[dict] = []
    candidates: list[tuple[str, str, Path, dict]] = []  # (kind, name, manifest path in project, manifest)
    base = read_json(project / BASE_MANIFEST)
    if base:
        candidates.append(("base", base.get("name", "agate"), BASE_MANIFEST, base))
    exp_dir = project / EXPANSIONS_DIR
    if exp_dir.is_dir():
        for path in sorted(exp_dir.glob("*.json")):
            manifest = read_json(path)
            candidates.append(("expansion", manifest.get("name", path.stem), EXPANSIONS_DIR / path.name, manifest))

    lock = pkgs.load_lock(project)["packages"]
    for kind, name, rel, manifest in candidates:
        entry = lock.get(name, {})
        recorded = ({"repo": entry.get("repo"), "path": entry.get("path"), "commit": entry.get("ref")}
                    if entry else manifest.get("source", {}))
        if kind == "base":
            repo, sub = split_source(base_from) if base_from else (recorded.get("repo") or DEFAULT_BASE_REPO, "")
        else:
            repo = recorded.get("repo") or hub_repo(project)
            sub = recorded.get("path") or f"{hub_extensions_path(project)}/{name}"
        row = {"kind": kind, "name": name, "installed": manifest.get("version", "?"),
               "installed_commit": recorded.get("commit"), "source": repo + (f"#{sub}" if sub else ""),
               "available": None, "available_commit": None, "status": "unknown"}
        tmp = Path(tempfile.mkdtemp(prefix="agate-check-"))
        try:
            tag = None if base_from else pkgs.release_ref(project, repo)
            folder, commit = fetch(repo, sub, tmp, tag)
            upstream = read_json(folder / rel)
            row["available"], row["available_commit"] = upstream.get("version"), commit
            if tag:  # releases: compare tags, never the branch tip
                row["installed"], row["available"] = entry.get("tag") or row["installed"], tag
            if not upstream:
                row["status"] = "missing upstream"
            elif tag:
                have = (entry.get("tag") or manifest.get("version") or "0").lstrip("v")
                row["status"] = ("update available" if version_tuple(tag.lstrip("v")) > version_tuple(have)
                                 else "up to date")
            elif version_tuple(upstream.get("version", "0")) > version_tuple(row["installed"]):
                row["status"] = "update available"
            elif commit and row["installed_commit"] and commit != row["installed_commit"]:
                row["status"] = "new commits (same version)"
            else:
                row["status"] = "up to date"
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, RuntimeError) as exc:
            row["status"] = f"unreachable ({exc.__class__.__name__})"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        rows.append(row)
    return rows


def print_check(rows: list[dict]) -> None:
    if not rows:
        print("Nothing installed to check (no .agate/manifest.json).")
        return
    for row in rows:
        label = "Agate" if row["kind"] == "base" else f"Extension {row['name']}"
        available = row["available"] or "?"
        print(f"- {label}: installed {row['installed']}, available {available} → {row['status']}")
        print(f"    source: {row['source']}")
    if any(r["status"].startswith(("update", "new commits")) for r in rows):
        print("To update: python3 .agate/agate.py update (shows what changes), then with --yes.")


def run_sync(project: Path, source_arg: str, dry_run: bool, consent: bool = True, ref: str | None = None) -> int:
    """Sync from a source. Repos that follow releases are installed from their latest tag (or `ref`).

    `consent=False` (an `add` without --yes): if the package brings scripts, print one line to ask the person first.
    """
    repo, sub = split_source(source_arg)
    tmp = Path(tempfile.mkdtemp(prefix="agate-sync-"))
    try:
        try:
            tag = ref or pkgs.release_ref(project, repo)
            upstream, commit = fetch(repo, sub, tmp, tag)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        except subprocess.CalledProcessError as exc:
            print(f"Could not download {source_arg}: {(exc.stderr or '').strip()}", file=sys.stderr)
            return 2
        if not upstream.is_dir():
            print(f"Not found: {source_arg}", file=sys.stderr)
            return 2
        if upstream.resolve() == project:
            print("Source and project are the same folder: nothing to do.")
            return 1
        if not dry_run and not consent:
            scripts = pkgs.script_files(upstream)
            if scripts:
                name = sub.rsplit("/", 1)[-1] if sub else Path(repo).name
                print(pkgs.consent_line(name, f"{repo}{'@' + tag if tag else ''}", "own", scripts))
                return 3
        repo_value = repo if is_url(repo) else str(Path(repo).expanduser().resolve())
        report = sync(project, upstream, dry_run=dry_run,
                      source={"repo": repo_value, "path": sub, "commit": commit, "tag": tag})
        print_report(report, dry_run)
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    default_project = str(Path(__file__).resolve().parents[3])

    if argv and argv[0] == "add":
        parser = argparse.ArgumentParser(prog="sync.py add", description="Install or update an extension from the hub.")
        parser.add_argument("name", help="extension name (folder in the hub's extensions/)")
        parser.add_argument("--hub", help="hub path or URL (default: source 'agate' in .agate/library.json)")
        parser.add_argument("--project", default=default_project)
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(argv[1:])
        project = Path(args.project).resolve()
        hub = args.hub or hub_repo(project)
        return run_sync(project, f"{hub}#{hub_extensions_path(project)}/{args.name}", args.dry_run)

    if argv and argv[0] in ("check", "status"):
        parser = argparse.ArgumentParser(prog="sync.py check", description="List available updates; changes nothing.")
        parser.add_argument("--from", dest="source", help="base path or URL (default: recorded source or the official repo)")
        parser.add_argument("--project", default=default_project)
        args = parser.parse_args(argv[1:])
        print_check(check(Path(args.project).resolve(), args.source))
        return 0

    parser = argparse.ArgumentParser(description="Sync this project with the Agate base or an extension.",
                                     epilog="Also: `sync.py add <extension>` and `sync.py check`.")
    parser.add_argument("--from", dest="source",
                        help="local path or git URL of the base or an extension; add #<sub-path> for a hub folder")
    parser.add_argument("--project", default=default_project, help="project root (default: this script's project)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, without writing")
    parser.add_argument("--check", action="store_true", help="only list available updates (same as `sync.py check`)")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    if args.check:
        print_check(check(project, args.source))
        return 0
    if not args.source:
        parser.error("--from is required (or use `sync.py add <extension>` / `sync.py check`)")
    return run_sync(project, args.source, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
