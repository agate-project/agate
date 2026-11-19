#!/usr/bin/env python3
"""Registry of this project's chats across all harnesses (Orca, Claude Code, OpenCode, Codex, Gemini).

It does not copy conversations: it stores REFERENCES (where each chat lives in each harness) in
memory/local/chats.json, which is not committed. One chat can have several references (for example, the Orca tab
and the Claude Code session running underneath).

Usage (from any folder in the repo):
    python3 .agate/agate.py chats scan                  # find this repo's chats and update the registry
    python3 .agate/agate.py chats list [--limit 20]
    python3 .agate/agate.py chats search "text"         # search inside the conversations
    python3 .agate/agate.py chats show <id> [--last 20] # condensed, readable version (person and agent text only)
    python3 .agate/agate.py chats resume <id>           # how to reopen it in each harness
    python3 .agate/agate.py chats note <id>|--latest --summary "…" [--produced path …] [--title "…"]

What `search` and `show` print is only for reading here: it is never copied to memory/shared/ or artifacts/.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()


# ---------------------------------------------------------------- helpers
def env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser() if v else default


def orca_db() -> Path:
    return env_path("AGATE_ORCA_DB", HOME / ".config/orca/agent-session-journal.db")


def opencode_db() -> Path:
    return env_path("AGATE_OPENCODE_DB", HOME / ".local/share/opencode/opencode.db")


def codex_dir() -> Path:
    return env_path("AGATE_CODEX_DIR", HOME / ".codex/sessions")


def gemini_dir() -> Path:
    return env_path("AGATE_GEMINI_DIR", HOME / ".gemini/tmp")


def default_claude_home() -> Path:
    return env_path("CLAUDE_CONFIG_DIR", HOME / ".claude")


def ro(db: Path) -> sqlite3.Connection:
    """Open a SQLite database read-only (other harnesses' data is never written)."""
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def iso(ts) -> str:
    """Milliseconds, seconds or ISO text → YYYY-MM-DDTHH:MM (UTC)."""
    if ts is None or ts == "":
        return ""
    if isinstance(ts, str):
        return ts[:16]
    ts = float(ts)
    if ts > 1e11:
        ts /= 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")


def slugify(s: str, n: int = 40) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:n].strip("-") or "chat"


def short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


TURN_RE = re.compile(r'"type":\s*"(user|assistant)"')
USER_RE = re.compile(r'"type":\s*"user"')
SYS_TAGS = re.compile(r"<(system-reminder|task-notification|command-[a-z-]+|local-command-[a-z-]+)>.*?</\1>", re.S)


def clean(text: str) -> str:
    return SYS_TAGS.sub("", text or "").strip()


# ---------------------------------------------------------------- repo identity
_ident_cache: dict[str, tuple] = {}


def git(path: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def norm_remote(url: str) -> str:
    u = url.strip().lower()
    u = re.sub(r"^(https?://|ssh://|git@)", "", u)
    u = u.replace(":", "/").removesuffix(".git").rstrip("/")
    u = re.sub(r"^[^@/]+@", "", u)  # credentials in the URL
    return u


def ident(path: str | Path) -> tuple:
    """(git common dir, normalized remote) of a folder; empty if missing or not git."""
    key = str(path)
    if key not in _ident_cache:
        p = Path(path)
        if not p.is_dir():
            _ident_cache[key] = ("", "")
        else:
            common = git(p, "rev-parse", "--path-format=absolute", "--git-common-dir")
            remote = norm_remote(git(p, "config", "--get", "remote.origin.url"))
            _ident_cache[key] = (common, remote)
    return _ident_cache[key]


class Repo:
    """This project's repo: its root, its worktrees and its identity (to recognize copies at other paths)."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.common, self.remote = ident(self.root)
        self.paths = {str(self.root)}
        wt = git(self.root, "worktree", "list", "--porcelain")
        for line in wt.splitlines():
            if line.startswith("worktree "):
                self.paths.add(str(Path(line[9:]).resolve()))

    def owns(self, path: str) -> bool:
        if not path:
            return False
        p = str(Path(path).expanduser())
        if p in self.paths or any(p.startswith(x + os.sep) for x in self.paths):
            return True
        common, remote = ident(p)
        return bool((common and common == self.common) or (remote and remote == self.remote))


def find_root(start: Path) -> Path:
    top = git(start, "rev-parse", "--show-toplevel")
    if top:
        return Path(top)
    for p in [start, *start.parents]:
        if (p / "AGENTS.md").exists():
            return p
    return start


# ---------------------------------------------------------------- conversation readers
def read_claude(path: Path):
    """Turns (role, text) of a Claude Code .jsonl: text only, no tools or reminders."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not TURN_RE.search(line):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain") or d.get("type") not in ("user", "assistant"):
                continue
            c = (d.get("message") or {}).get("content")
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                text = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            else:
                text = ""
            text = clean(text)
            if text:
                yield ("person" if d["type"] == "user" else "agent", text)


def read_opencode(db: Path, session: str):
    con = ro(db)
    try:
        msgs = con.execute("select id, data from message where session_id=? order by time_created", (session,)).fetchall()
        for mid, data in msgs:
            role = (json.loads(data) or {}).get("role", "")
            parts = con.execute("select data from part where message_id=? order by time_created", (mid,)).fetchall()
            text = "\n".join(json.loads(p[0]).get("text", "") for p in parts if json.loads(p[0]).get("type") == "text")
            text = clean(text)
            if text:
                yield ("person" if role == "user" else "agent", text)
    finally:
        con.close()


def read_codex(path: Path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            p = d.get("payload") or {}
            if d.get("type") == "response_item" and p.get("type") == "message":
                text = "\n".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict))
                text = clean(text)
                if text and p.get("role") in ("user", "assistant"):
                    yield ("person" if p["role"] == "user" else "agent", text)


def read_gemini(path: Path):
    d = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    for m in d.get("messages", []):
        c = m.get("content")
        text = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in (c or []) if isinstance(x, dict))
        text = clean(text)
        if text:
            yield ("person" if m.get("type") == "user" else "agent", text)


def turns(chat: dict):
    """First readable transcript among the chat's references."""
    order = ["claude-code", "opencode", "codex", "gemini"]
    for ref in sorted(chat.get("refs", []), key=lambda r: order.index(r["harness"]) if r["harness"] in order else 9):
        try:
            h = ref["harness"]
            if h == "claude-code" and ref.get("path") and Path(ref["path"]).exists():
                return list(read_claude(Path(ref["path"]))), h
            if h == "opencode" and ref.get("db") and Path(ref["db"]).exists():
                return list(read_opencode(Path(ref["db"]), ref["session"])), h
            if h == "codex" and ref.get("path") and Path(ref["path"]).exists():
                return list(read_codex(Path(ref["path"]))), h
            if h == "gemini" and ref.get("path") and Path(ref["path"]).exists():
                return list(read_gemini(Path(ref["path"]))), h
        except (OSError, ValueError, sqlite3.Error, KeyError, AttributeError) as e:
            print(f"warning: could not read {ref.get('harness')}: the format may have changed ({e})", file=sys.stderr)
    return [], None


# ---------------------------------------------------------------- discovery adapters (scan)
class Found:
    """Chats found in this pass, merged by session."""

    def __init__(self):
        self.chats: list[dict] = []
        self.by_ref: dict[tuple, dict] = {}
        self.warnings: list[str] = []
        self.counts: dict[str, int] = {}

    def get(self, harness: str, session: str) -> dict | None:
        return self.by_ref.get((harness, session))

    def new(self) -> dict:
        c = {"title": "", "created": "", "updated": "", "refs": []}
        self.chats.append(c)
        return c

    def add_ref(self, chat: dict, ref: dict):
        key = (ref["harness"], ref["session"])
        for r in chat["refs"]:
            if (r["harness"], r["session"]) == key:
                r.update({k: v for k, v in ref.items() if v})
                break
        else:
            chat["refs"].append(ref)
        self.by_ref[key] = chat

    def touch(self, chat: dict, title="", created="", updated="", prefer=False):
        if title and (prefer or not chat["title"]):
            chat["title"] = short(title, 90)
        if created and (not chat["created"] or created < chat["created"]):
            chat["created"] = created
        if updated and updated > chat["updated"]:
            chat["updated"] = updated


def claude_homes() -> list[Path]:
    homes = []
    extra = os.environ.get("AGATE_CLAUDE_HOMES")
    if extra:
        homes += [Path(p).expanduser() for p in extra.split(os.pathsep) if p]
    else:
        homes.append(default_claude_home())
        db = orca_db()
        if db.exists():
            try:
                con = ro(db)
                for (rec,) in con.execute("select record_json from agent_session_records"):
                    p = ((json.loads(rec).get("accountHome") or {}).get("path"))
                    if p:
                        homes.append(Path(p))
                con.close()
            except (sqlite3.Error, ValueError):
                pass
    out = []
    for h in homes:
        h = h.expanduser()
        if h not in out:
            out.append(h)
    return out


def scan_orca(repo: Repo, f: Found):
    db = orca_db()
    if not db.exists():
        return
    n = 0
    try:
        con = ro(db)
        rows = con.execute("select record_json from agent_session_records").fetchall()
        con.close()
    except sqlite3.Error as e:
        f.warnings.append(f"Orca: could not read the database ({e}); the format may have changed")
        return
    for (rec,) in rows:
        try:
            r = json.loads(rec)
            ws = (r.get("location") or {}).get("workspaceId", "")
            path = ws.split("::", 1)[1] if "::" in ws else ""
            if not repo.owns(path):
                continue
            sid = r["sessionId"]  # if missing, the record cannot be referenced: warned below
            chain = r.get("providerHandleChain") or []
            if not isinstance(sid, str) or not isinstance(chain, list):
                raise TypeError("sessionId or providerHandleChain in a different format")
            chat = f.new()
            account = (r.get("accountHome") or {}).get("path") or ""
            f.add_ref(chat, {"harness": "orca", "session": sid, "db": str(db), "workspace": path,
                             "provider": r.get("provider", ""), "model": (r.get("options") or {}).get("model", "")})
            for link in chain:
                h = link.get("handle") or {}
                if h.get("provider") == "claude" and h.get("sessionId"):
                    f.add_ref(chat, {"harness": "claude-code", "session": h["sessionId"], "account": account,
                                     "cwd": path, "continued_from": "orca"})
                elif h.get("agent") == "opencode" and h.get("nativeId"):
                    f.add_ref(chat, {"harness": "opencode", "session": h["nativeId"], "cwd": path,
                                     "continued_from": "orca"})
            f.touch(chat, r.get("conversationName", ""), iso(r.get("createdAt")), iso(r.get("updatedAt")), prefer=True)
            n += 1
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            f.warnings.append(f"Orca: a record has a different format ({e}); skipped")
    f.counts["orca"] = n


def jsonl_meta(path: Path) -> dict:
    """cwd, title and dates of a Claude Code .jsonl, reading as little as possible."""
    meta = {"cwd": "", "title": "", "first": "", "created": "", "updated": ""}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not meta["cwd"] and '"cwd"' in line:
                m = re.search(r'"cwd":\s*"((?:[^"\\]|\\.)*)"', line)
                if m:
                    meta["cwd"] = json.loads(f'"{m.group(1)}"')
            if '"ai-title"' in line:
                try:
                    meta["title"] = json.loads(line).get("aiTitle", "") or meta["title"]
                except ValueError:
                    pass
            ts = re.search(r'"timestamp":\s*"([^"]+)"', line)
            if ts:
                meta["created"] = meta["created"] or ts.group(1)[:16]
                meta["updated"] = ts.group(1)[:16]
            if not meta["first"] and USER_RE.search(line):
                try:
                    d = json.loads(line)
                    c = (d.get("message") or {}).get("content")
                    text = c if isinstance(c, str) else " ".join(
                        b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
                    meta["first"] = short(clean(text), 80)
                except ValueError:
                    pass
    return meta


def claude_slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def scan_claude(repo: Repo, f: Found):
    n = 0
    seen: set[str] = set()  # Orca account profiles may share the same projects/ folder
    for home in claude_homes():
        projects = home / "projects"
        if not projects.is_dir():
            continue
        slugs = {claude_slug(p) for p in repo.paths}
        for d in sorted(projects.iterdir()):
            if not d.is_dir():
                continue
            files = sorted(d.glob("*.jsonl"))
            if not files:
                continue
            ok = d.name in slugs
            if not ok:  # another path of the same repo (worktree, another copy): recognized by its cwd
                try:
                    cwd = jsonl_meta(files[-1])["cwd"]
                except OSError:
                    cwd = ""
                ok = repo.owns(cwd)
            if not ok:
                continue
            for fp in files:
                real = os.path.realpath(fp)
                if real in seen:
                    continue
                seen.add(real)
                try:
                    meta = jsonl_meta(fp)
                except OSError as e:
                    f.warnings.append(f"Claude Code: could not read {fp.name} ({e})")
                    continue
                sid = fp.stem
                chat = f.get("claude-code", sid)
                known = next((r for r in chat["refs"] if r["session"] == sid), {}) if chat else {}
                chat = chat or f.new()
                # The account recorded by Orca wins (it is the one it ran with); otherwise, the folder holding the file.
                ref = {"harness": "claude-code", "session": sid, "path": str(fp),
                       "account": known.get("account") or str(home), "cwd": meta["cwd"]}
                f.add_ref(chat, ref)
                f.touch(chat, meta["title"] or meta["first"], meta["created"], meta["updated"])
                n += 1
    f.counts["claude-code"] = n


def scan_opencode(repo: Repo, f: Found):
    db = opencode_db()
    if not db.exists():
        return
    n = 0
    try:
        con = ro(db)
        rows = con.execute("select id, directory, title, time_created, time_updated from session").fetchall()
        con.close()
    except sqlite3.Error as e:
        f.warnings.append(f"OpenCode: could not read the database ({e}); the format may have changed")
        return
    for sid, directory, title, created, updated in rows:
        if not repo.owns(directory or ""):
            continue
        chat = f.get("opencode", sid) or f.new()
        f.add_ref(chat, {"harness": "opencode", "session": sid, "db": str(db), "cwd": directory})
        f.touch(chat, title or "", iso(created), iso(updated))
        n += 1
    f.counts["opencode"] = n


def scan_codex(repo: Repo, f: Found):
    base = codex_dir()
    if not base.is_dir():
        return
    n = 0
    for fp in glob.glob(str(base / "**" / "rollout-*.jsonl"), recursive=True):
        try:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                first = json.loads(fh.readline() or "{}")
            p = first.get("payload") or first
            sid, cwd = p.get("id") or Path(fp).stem, p.get("cwd", "")
        except (OSError, ValueError) as e:
            f.warnings.append(f"Codex: the format changed ({e})")
            continue
        if not repo.owns(cwd):
            continue
        chat = f.get("codex", sid) or f.new()
        f.add_ref(chat, {"harness": "codex", "session": sid, "path": fp, "cwd": cwd})
        f.touch(chat, "", iso(p.get("timestamp")), iso(os.path.getmtime(fp)))
        n += 1
    f.counts["codex"] = n


def scan_gemini(repo: Repo, f: Found):
    base = gemini_dir()
    if not base.is_dir():
        return
    n = 0
    for root in repo.paths:  # Gemini CLI groups by a hash of the project path
        d = base / hashlib.sha256(root.encode()).hexdigest() / "chats"
        for fp in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                data = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
            except (OSError, ValueError) as e:
                f.warnings.append(f"Gemini: the format changed ({e})")
                continue
            sid = data.get("sessionId") or fp.stem
            chat = f.get("gemini", sid) or f.new()
            f.add_ref(chat, {"harness": "gemini", "session": sid, "path": str(fp), "cwd": root})
            f.touch(chat, "", iso(data.get("startTime")), iso(data.get("lastUpdated") or os.path.getmtime(fp)))
            n += 1
    f.counts["gemini"] = n


ADAPTERS = [scan_orca, scan_claude, scan_opencode, scan_codex, scan_gemini]


# ---------------------------------------------------------------- registry
class Registry:
    def __init__(self, path: Path):
        self.path = path
        self.chats: list[dict] = []
        if path.exists():
            try:
                self.chats = json.loads(path.read_text(encoding="utf-8")).get("chats", [])
            except ValueError:
                print(f"warning: {path} is not valid JSON; leaving it untouched and starting a new one in memory",
                      file=sys.stderr)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.chats.sort(key=lambda c: c.get("updated", ""), reverse=True)
        data = {"note": "Local references to this project's chats. Not committed. Generated by chats.py.",
                "chats": self.chats}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def find(self, cid: str) -> dict | None:
        for c in self.chats:
            if c["id"] == cid:
                return c
        hits = [c for c in self.chats if c["id"].startswith(cid) or any(r["session"].startswith(cid) for r in c["refs"])]
        return hits[0] if len(hits) == 1 else None

    def merge(self, found: Found) -> tuple[int, int]:
        index = {(r["harness"], r["session"]): c for c in self.chats for r in c.get("refs", [])}
        used = {c["id"] for c in self.chats}
        new = upd = 0
        for fc in found.chats:
            hit = next((index[(r["harness"], r["session"])] for r in fc["refs"] if (r["harness"], r["session"]) in index), None)
            if hit is None:
                base = f"{(fc['created'] or fc['updated'] or '0000-00-00')[:10]}-{slugify(fc['title'])}"
                cid, i = base, 2
                while cid in used:
                    cid, i = f"{base}-{i}", i + 1
                used.add(cid)
                hit = {"id": cid, "title": "", "created": "", "updated": "", "summary": "", "produced": [], "refs": []}
                self.chats.append(hit)
                new += 1
            else:
                upd += 1
            keys = {(r["harness"], r["session"]): r for r in hit["refs"]}
            for r in fc["refs"]:
                k = (r["harness"], r["session"])
                if k in keys:
                    keys[k].update({a: b for a, b in r.items() if b})
                else:
                    hit["refs"].append(r)
                index[k] = hit
            if fc["title"] and not hit.get("title_locked"):
                hit["title"] = fc["title"]
            hit["title"] = hit["title"] or "(untitled)"
            hit["created"] = min(filter(None, [hit.get("created"), fc["created"]]), default="")
            hit["updated"] = max(filter(None, [hit.get("updated"), fc["updated"]]), default="")
        return new, upd


# ---------------------------------------------------------------- commands
def resume_lines(chat: dict) -> list[str]:
    out = []
    default_home = str(default_claude_home())
    for r in chat.get("refs", []):
        h = r["harness"]
        if h == "orca":
            out.append(f"Orca: open the workspace {r.get('workspace', '')} and the chat \"{chat.get('title', '')}\".")
        elif h == "claude-code":
            prefix = "" if not r.get("account") or r["account"] == default_home else f"CLAUDE_CONFIG_DIR={r['account']} "
            where = r.get("cwd") or ""
            out.append(f"Claude Code: (cd {where} && {prefix}claude --resume {r['session']})" if where
                       else f"Claude Code: {prefix}claude --resume {r['session']}")
        elif h == "opencode":
            out.append(f"OpenCode: opencode --session {r['session']}")
        elif h == "codex":
            out.append(f"Codex: codex resume {r['session']}")
        elif h == "gemini":
            out.append(f"Gemini CLI: gemini --resume {r['session']}  (if your version supports it; otherwise, /chat resume)")
    return out


def cmd_scan(reg: Registry, repo: Repo, args) -> int:
    found = Found()
    for adapter in ADAPTERS:
        try:
            adapter(repo, found)
        except Exception as e:  # one broken harness does not stop the others
            found.warnings.append(f"{adapter.__name__[5:]}: discovery failed ({e}); the format may have changed")
    new, upd = reg.merge(found)
    if not args.dry_run:
        reg.save()
    counts = ", ".join(f"{k}: {v}" for k, v in found.counts.items()) or "no harness found"
    print(f"Chats of this repo: {len(found.chats)} ({counts}).")
    print(f"Registry: {new} new, {upd} updated, {len(reg.chats)} in total"
          + (" (dry run: not saved)." if args.dry_run else f" → {reg.path}"))
    for w in found.warnings:
        print("warning:", w)
    return 0


def cmd_list(reg: Registry, args) -> int:
    rows = [c for c in reg.chats if not args.harness or any(r["harness"] == args.harness for r in c["refs"])]
    if not rows:
        print("The registry is empty. Run first: python3 .agate/agate.py chats scan")
        return 0
    for c in rows[: args.limit]:
        hs = ",".join(sorted({r["harness"] for r in c["refs"]}))
        extra = f" — {c['summary']}" if c.get("summary") else ""
        print(f"{c['updated'][:10]}  {c['id']}  [{hs}]  {c['title']}{extra}")
    return 0


def cmd_search(reg: Registry, args) -> int:
    q = args.text if args.case else args.text.lower()
    hits = 0
    for c in reg.chats:
        meta = " ".join([c.get("title", ""), c.get("summary", "")])
        meta_hit = q in (meta if args.case else meta.lower())
        ts, _ = turns(c)
        snippets = []
        for role, text in ts:
            hay = text if args.case else text.lower()
            i = hay.find(q)
            if i >= 0:
                a = max(0, i - 80)
                snippets.append(f"  {role}: …{short(text[a:i + len(q) + 120], 200)}…")
            if len(snippets) >= args.per_chat:
                break
        if snippets or meta_hit:
            hits += 1
            print(f"{c['id']}  {c['title']}")
            print("\n".join(snippets) if snippets else "  (title or summary matches)")
            if hits >= args.limit:
                break
    if not hits:
        print("No results." + ("" if reg.chats else " The registry is empty: run `scan` first."))
    return 0


def cmd_show(reg: Registry, args) -> int:
    c = reg.find(args.id)
    if not c:
        print(f"Chat '{args.id}' not found (or several start like that). See `list`.", file=sys.stderr)
        return 2
    ts, harness = turns(c)
    print(f"# {c['title']}  ({c['id']}, read from {harness or 'no harness'})")
    if c.get("summary"):
        print(f"Summary: {c['summary']}")
    for role, text in (ts[-args.last:] if args.last else ts):
        print(f"\n[{role}] {text if len(text) <= args.max else text[:args.max] + ' […]'}")
    if not ts:
        print("No readable transcript on this machine (the chat may be on another machine or in another format).")
    return 0


def cmd_resume(reg: Registry, args) -> int:
    c = reg.find(args.id)
    if not c:
        print(f"Chat '{args.id}' not found. See `list`.", file=sys.stderr)
        return 2
    print(f"{c['title']} ({c['id']})")
    for line in resume_lines(c):
        print(" -", line)
    return 0


def cmd_note(reg: Registry, args) -> int:
    if args.latest:
        c = reg.chats and max(reg.chats, key=lambda x: x.get("updated", ""))
    else:
        c = reg.find(args.id or "")
    if not c:
        print("Chat not found. Use an id from `list` or --latest (run `scan` first).", file=sys.stderr)
        return 2
    if args.summary:
        c["summary"] = short(args.summary, 300)
    if args.title:
        c["title"], c["title_locked"] = short(args.title, 90), True
    for p in args.produced or []:
        if p not in c.setdefault("produced", []):
            c["produced"].append(p)
    reg.save()
    print(f"Noted on {c['id']}: {c.get('summary', '')}")
    return 0


PASSTHROUGH = {"chats": "past chats of this repo in any harness: scan, list, search, show, resume, note"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Local registry of the project's chats across all harnesses.")
    ap.add_argument("--root", help="repo root (default: the current directory's)")
    ap.add_argument("--registry", help="registry file (default memory/local/chats.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="find this repo's chats and update the registry")
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("list")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--harness")
    s = sub.add_parser("search")
    s.add_argument("text")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--per-chat", type=int, default=3)
    s.add_argument("--case", action="store_true", help="case-sensitive")
    s = sub.add_parser("show")
    s.add_argument("id")
    s.add_argument("--last", type=int, default=0, help="only the last N turns")
    s.add_argument("--max", type=int, default=1500, help="characters per turn")
    s = sub.add_parser("resume")
    s.add_argument("id")
    s = sub.add_parser("note")
    s.add_argument("id", nargs="?")
    s.add_argument("--latest", action="store_true", help="the most recently updated chat")
    s.add_argument("--summary")
    s.add_argument("--title")
    s.add_argument("--produced", nargs="*")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else find_root(Path.cwd())
    reg = Registry(Path(args.registry) if args.registry else root / "memory/local/chats.json")
    if args.cmd == "scan":
        return cmd_scan(reg, Repo(root), args)
    return {"list": cmd_list, "search": cmd_search, "show": cmd_show, "resume": cmd_resume,
            "note": cmd_note}[args.cmd](reg, args)


if __name__ == "__main__":
    sys.exit(main())
