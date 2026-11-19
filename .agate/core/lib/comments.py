"""Comments on canvases and HTML artifacts.

People leave comments from the browser (`agate.py serve` + the canvas or the `comments.js` overlay). They are stored
next to the artifact, as plain JSON, and committed: team feedback is project knowledge.
- a canvas folder `artifacts/…/x.canvas/` → `artifacts/…/x.canvas/comments.json`
- an HTML file `artifacts/…/x.html` → `artifacts/…/x.comments.json`

The agent reads them only when they matter: `agate.py start` shows one line when there are new ones, and
`agate.py comments list --new` prints them compactly. `seen` marks them as read (memory/local/state.json).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import sys
import threading
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

STATE = Path("memory/local/state.json")
ARTIFACTS = "artifacts/"
MAX_TEXT = 4000          # characters per comment or reply
MAX_THREADS = 2000       # threads per artifact
MAX_REPLIES = 200        # replies per thread
MAX_AUTHOR = 80
MAX_ANCHOR = 2000        # bytes of the anchor object
LIST_TEXT = 200          # characters per line in `list`
LIST_MAX = 20            # lines before "+N more"
SEVERITY = 3             # start.py orders ascending: 0 = most severe
AGENT = "agent"
_LOCK = threading.Lock()


class CommentError(ValueError):
    """Bad request (path outside artifacts/, too long, unknown id…)."""


# ---------------------------------------------------------------- paths

def now() -> str:
    fixed = os.environ.get("AGATE_NOW")
    if fixed:
        return fixed
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize(file: str) -> str:
    """Canonical artifact key: 'artifacts/…/x.canvas/' (folder) or 'artifacts/…/x.html'. Raises CommentError."""
    raw = (file or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw or raw.startswith("/") or re.match(r"^[a-zA-Z]:", raw):
        raise CommentError("file must be a relative path inside artifacts/")
    is_dir = raw.endswith("/")
    raw = re.sub(r"/index\.html?$", "/", raw)
    is_dir = is_dir or raw.endswith("/")
    parts = [p for p in PurePosixPath(raw).parts if p not in ("", ".")]
    if not parts or parts[0] != "artifacts" or ".." in parts or any(p.startswith(".") for p in parts):
        raise CommentError("file must be inside artifacts/")
    key = "/".join(parts)
    return key + "/" if is_dir else key


def store_path(root: Path, file: str) -> tuple[str, Path]:
    """(key, path of its comments file). The artifact must exist and stay inside artifacts/."""
    key = normalize(file)
    base = (root / ARTIFACTS).resolve()
    target = (root / key).resolve()
    if target != base and base not in target.parents:
        raise CommentError("file must be inside artifacts/")
    if key.endswith("/"):
        if not target.is_dir():
            raise CommentError("artifact folder not found")
        return key, target / "comments.json"
    if not target.is_file() or target.suffix.lower() not in (".html", ".htm"):
        raise CommentError("artifact not found (an .html file or a canvas folder)")
    return key, target.with_name(target.stem + ".comments.json")


def comment_files(root: Path) -> list[tuple[str, Path]]:
    """Every comments file under artifacts/, as (artifact key, path)."""
    base = root / ARTIFACTS
    found = []
    if not base.is_dir():
        return found
    for path in sorted(base.rglob("*comments.json")):
        rel = path.relative_to(root).as_posix()
        if path.name == "comments.json":
            found.append((rel[: -len("comments.json")], path))
        elif path.name.endswith(".comments.json"):
            stem = rel[: -len(".comments.json")]
            html = next((stem + ext for ext in (".html", ".htm") if (root / (stem + ext)).is_file()), stem + ".html")
            found.append((html, path))
    return found


# ---------------------------------------------------------------- store

def load(path: Path, key: str = "") -> dict:
    if not path.is_file():
        return {"file": key, "comments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"file": key, "comments": []}
    if not isinstance(data, dict) or not isinstance(data.get("comments"), list):
        return {"file": key, "comments": []}
    data.setdefault("file", key)
    return data


def _save(path: Path, data: dict) -> None:
    data["updated"] = now()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _clean_text(text) -> str:
    text = str(text if text is not None else "").replace("\r\n", "\n").strip()
    if not text:
        raise CommentError("empty text")
    if len(text) > MAX_TEXT:
        raise CommentError(f"text too long (max {MAX_TEXT} characters)")
    return text


def _clean_author(author) -> str:
    author = re.sub(r"[\x00-\x1f]", " ", str(author or "")).strip()[:MAX_AUTHOR]
    return author or "anonymous"


def _clean_anchor(anchor) -> dict:
    if anchor is None:
        return {"kind": "page"}
    if not isinstance(anchor, dict):
        raise CommentError("anchor must be an object")
    if len(json.dumps(anchor)) > MAX_ANCHOR:
        raise CommentError("anchor too large")
    keep = {}
    for k, v in anchor.items():
        if not isinstance(k, str) or len(k) > 40:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            keep[k] = round(float(v), 4)
        elif isinstance(v, str):
            keep[k] = v[:400]
    keep.setdefault("kind", "page")
    return keep


def add(root: Path, file: str, text, author=None, anchor=None) -> dict:
    key, path = store_path(root, file)
    with _LOCK:
        data = load(path, key)
        if len(data["comments"]) >= MAX_THREADS:
            raise CommentError("too many comments on this artifact")
        entry = {"id": "c" + secrets.token_hex(4), "anchor": _clean_anchor(anchor), "text": _clean_text(text),
                 "author": _clean_author(author), "created": now(), "replies": [], "resolved": False}
        data["file"] = key
        data["comments"].append(entry)
        _save(path, data)
    return entry


def _find(root: Path, cid: str, file: str | None = None):
    pairs = [store_path(root, file)] if file else comment_files(root)
    for key, path in pairs:
        data = load(path, key)
        for entry in data["comments"]:
            if entry.get("id") == cid:
                return key, path, data, entry
    raise CommentError(f"comment {cid} not found")


def reply(root: Path, cid: str, text, author=None, file: str | None = None) -> dict:
    with _LOCK:
        key, path, data, entry = _find(root, cid, file)
        replies = entry.setdefault("replies", [])
        if len(replies) >= MAX_REPLIES:
            raise CommentError("too many replies")
        new = {"id": "r" + secrets.token_hex(4), "text": _clean_text(text), "author": _clean_author(author),
               "created": now()}
        replies.append(new)
        _save(path, data)
    return new


def resolve(root: Path, cid: str, resolved: bool = True, author=None, file: str | None = None) -> dict:
    with _LOCK:
        key, path, data, entry = _find(root, cid, file)
        entry["resolved"] = bool(resolved)
        if resolved:
            entry["resolved_by"], entry["resolved_at"] = _clean_author(author), now()
        else:
            entry.pop("resolved_by", None)
            entry.pop("resolved_at", None)
        _save(path, data)
    return entry


# ---------------------------------------------------------------- seen / new

def _state(root: Path) -> dict:
    path = root / STATE
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(root: Path, state: dict) -> None:
    path = root / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def new_items(root: Path, file: str | None = None) -> list[dict]:
    """Threads and replies newer than the last `seen`, not written by the agent. Oldest first."""
    seen = _state(root).get("comments_seen", {})
    pairs = [store_path(root, file)] if file else comment_files(root)
    items = []
    for key, path in pairs:
        last = seen.get(key, "")
        for entry in load(path, key)["comments"]:
            if entry.get("created", "") > last and entry.get("author") != AGENT:
                items.append({"type": "comment", "file": key, **entry})
            for r in entry.get("replies", []):
                if r.get("created", "") > last and r.get("author") != AGENT:
                    items.append({"type": "reply", "file": key, "parent": entry.get("id"), **r})
    return sorted(items, key=lambda i: i.get("created", ""))


def mark_seen(root: Path, file: str | None = None) -> int:
    state = _state(root)
    seen = state.setdefault("comments_seen", {})
    pairs = [store_path(root, file)] if file else comment_files(root)
    stamp = now()
    for key, _ in pairs:
        seen[key] = stamp
    _write_state(root, state)
    return len(pairs)


def attention(root: Path) -> list[dict]:
    """For `agate.py start`: one line when people left comments the agent hasn't seen; nothing otherwise."""
    try:
        items = new_items(root)
    except Exception:  # noqa: BLE001
        return []
    if not items:
        return []
    files = sorted({i["file"] for i in items})
    authors = sorted({i.get("author", "anonymous") for i in items})
    who = ", ".join(authors[:3]) + (f" +{len(authors) - 3}" if len(authors) > 3 else "")
    where = files[0] if len(files) == 1 else f"{len(files)} artifacts"
    n = len(items)
    text = (f"{n} new comment{'s' if n != 1 else ''} on {where} (by {who}) → ask the person whether to address them "
            "now; read with `python3 .agate/agate.py comments list --new`")
    return [{"severity": SEVERITY, "text": text}]


# ---------------------------------------------------------------- CLI

def _short(text: str, limit: int = LIST_TEXT) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _anchor_label(anchor: dict) -> str:
    kind = anchor.get("kind", "page")
    if kind == "board":
        return "board:" + str(anchor.get("board", "?"))
    if kind == "canvas":
        return "canvas"
    if anchor.get("quote"):
        return "«" + _short(anchor["quote"], 40) + "»"
    if anchor.get("label"):
        return _short(anchor["label"], 40)
    return kind


def _lines(items: list[dict]) -> list[str]:
    out = []
    for i in items:
        if i["type"] == "reply":
            out.append(f"{i['parent']} ↳ {i['file']} · {i.get('author', '?')}: {_short(i.get('text', ''))}")
        else:
            state = " [resolved]" if i.get("resolved") else ""
            out.append(f"{i['id']} · {i['file']} · {_anchor_label(i.get('anchor', {}))} · {i.get('author', '?')}: "
                       f"{_short(i.get('text', ''))}{state}")
    return out


def cmd_comments(args) -> int:
    root = Path(args.root)
    try:
        if args.action == "list":
            if args.new:
                items = new_items(root, args.file)
            else:
                pairs = [store_path(root, args.file)] if args.file else comment_files(root)
                items = []
                for key, path in pairs:
                    for entry in load(path, key)["comments"]:
                        if args.all or not entry.get("resolved"):
                            items.append({"type": "comment", "file": key, **entry})
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
                return 0
            if not items:
                print("no new comments" if args.new else "no open comments")
                return 0
            lines = _lines(items)
            limit = len(lines) if args.full else LIST_MAX
            print("\n".join(lines[:limit]))
            if len(lines) > limit:
                print(f"+{len(lines) - limit} more (--full)")
            return 0
        if args.action == "reply":
            r = reply(root, args.id, args.text, author=AGENT, file=args.file)
            print(f"replied to {args.id} ({r['id']})")
            return 0
        if args.action == "resolve":
            resolve(root, args.id, resolved=not args.reopen, author=AGENT, file=args.file)
            print(f"{'reopened' if args.reopen else 'resolved'} {args.id}")
            return 0
        if args.action == "seen":
            n = mark_seen(root, args.file)
            print(f"marked as seen: {n} artifact{'s' if n != 1 else ''}")
            return 0
    except CommentError as exc:
        print(f"comments: {exc}", file=sys.stderr)
        return 2
    return 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("comments", help="comments people left on canvases and artifacts: list, reply, resolve, seen")
    ps = p.add_subparsers(dest="action", required=True, metavar="<action>")
    pl = ps.add_parser("list", help="open comments (or only new ones with --new)")
    pl.add_argument("--new", action="store_true", help="only comments and replies since the last `seen`")
    pl.add_argument("--all", action="store_true", help="include resolved threads")
    pl.add_argument("--file", help="one artifact (artifacts/…/x.canvas/ or artifacts/…/x.html)")
    pl.add_argument("--full", action="store_true", help=f"no {LIST_MAX}-line limit")
    pl.add_argument("--json", action="store_true")
    pr = ps.add_parser("reply", help="reply to a comment (as the agent)")
    pr.add_argument("id")
    pr.add_argument("text")
    pr.add_argument("--file")
    pv = ps.add_parser("resolve", help="mark a thread as resolved")
    pv.add_argument("id")
    pv.add_argument("--reopen", action="store_true")
    pv.add_argument("--file")
    pn = ps.add_parser("seen", help="mark current comments as read (start stops mentioning them)")
    pn.add_argument("--file")
    p.set_defaults(func=cmd_comments)
