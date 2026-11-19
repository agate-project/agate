"""`agate.py serve`: view artifacts and canvases locally, with comments.

A static server for artifacts/, documents/ and the canvas engine, bound to 127.0.0.1 only, plus a small JSON API
for comments (stored by comments.py next to each artifact). Nothing else in the project is served: never .env,
.git, memory/ or the rest of .agate/.

To open it from another device, use a private channel (the remote-preview skill's Tailscale link, or the Orca
browser). This server never binds to other interfaces.
"""
from __future__ import annotations

import collections
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import comments  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8090
MAX_BODY = 64 * 1024
STATIC_PREFIXES = ("artifacts/", "documents/", ".agate/core/canvas/")
API_HEADER = "X-Agate-Request"  # custom header: browsers can't send it cross-site without a CORS preflight we refuse
SERVE_STATE = Path("memory/local/serve.json")   # port + pid of the running viewer, for `serve notify`
POLL_SECONDS = 0.7         # file watcher interval
HEARTBEAT_SECONDS = 15     # SSE keep-alive comment
MAX_EVENTS = 500           # ring buffer of recent events
MAX_STREAMS = 64           # concurrent SSE clients
MAX_WATCHED = 50           # artifacts watched at once
MAX_FILES = 500            # files watched per artifact
PRESENCE_TTL = 30          # seconds a viewer stays listed without a heartbeat
MAX_VIEWERS = 50           # per artifact


# ---------------------------------------------------------------- live view (events, file watching, presence)

def belongs(key: str, path: str) -> bool:
    """Does a project path (posix, relative) belong to the artifact `key`?"""
    if key.endswith("/"):
        return path.startswith(key)
    stem = re.sub(r"\.html?$", "", key)
    return path == key or path == stem + ".comments.json" or path.startswith(stem + "/") or \
        path.startswith(stem + "_files/")


def artifact_files(root: Path, key: str) -> list[str]:
    """Files whose changes matter for an artifact: a canvas folder (canvas.json, boards/, comments.json…) or an html
    file with its comments file and same-stem asset folder. Bounded by MAX_FILES."""
    out: list[str] = []
    if key.endswith("/"):
        base = root / key
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file() and not any(part.startswith(".") for part in path.relative_to(base).parts):
                    out.append(path.relative_to(root).as_posix())
                    if len(out) >= MAX_FILES:
                        break
        return out
    stem = re.sub(r"\.html?$", "", key)
    for rel in (key, stem + ".comments.json"):
        if (root / rel).is_file():
            out.append(rel)
    for folder in (stem, stem + "_files"):
        d = root / folder
        if d.is_dir():
            for path in sorted(d.rglob("*")):
                if path.is_file():
                    out.append(path.relative_to(root).as_posix())
                    if len(out) >= MAX_FILES:
                        return out
    return out


class LiveHub:
    """In-memory event bus: a ring buffer of events, a watcher thread and viewer presence. Stdlib only."""

    def __init__(self, root: Path):
        self.root = root
        self.cond = threading.Condition()
        self.events: collections.deque = collections.deque(maxlen=MAX_EVENTS)
        self.seq = 0
        self.watched: dict[str, dict] = {}   # key -> {"subs": n, "mtimes": {path: mtime}}
        self.presence: dict[str, dict] = {}  # key -> {client_id: {"name", "at"}}
        self.streams = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def publish(self, payload: dict) -> int:
        with self.cond:
            self.seq += 1
            self.events.append((self.seq, payload))
            self.cond.notify_all()
            return self.seq

    def _mtimes(self, key: str) -> dict:
        found = {}
        for rel in artifact_files(self.root, key):
            try:
                found[rel] = (self.root / rel).stat().st_mtime_ns
            except OSError:
                continue
        return found

    def subscribe(self, key: str) -> bool:
        with self.cond:
            if self.streams >= MAX_STREAMS:
                return False
            if key not in self.watched:
                if len(self.watched) >= MAX_WATCHED:
                    idle = [k for k, w in self.watched.items() if w["subs"] <= 0]
                    if not idle:
                        return False
                    del self.watched[idle[0]]
                self.watched[key] = {"subs": 0, "mtimes": self._mtimes(key)}
            self.watched[key]["subs"] += 1
            self.streams += 1
            return True

    def unsubscribe(self, key: str) -> None:
        with self.cond:
            self.streams = max(0, self.streams - 1)
            if key in self.watched:
                self.watched[key]["subs"] -= 1

    def wait(self, after: int, timeout: float) -> list[tuple[int, dict]]:
        with self.cond:
            if self.seq <= after:
                self.cond.wait(timeout)
            return [(n, e) for n, e in self.events if n > after]

    def _watch(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            with self.cond:
                keys = [k for k, w in self.watched.items() if w["subs"] > 0]
            for key in keys:
                now = self._mtimes(key)
                with self.cond:
                    w = self.watched.get(key)
                    if not w:
                        continue
                    before, w["mtimes"] = w["mtimes"], now
                changed = [p for p in now if before.get(p) != now[p]] + [p for p in before if p not in now]
                for path in changed:
                    self.publish({"type": "changed", "path": path})

    def touch_presence(self, key: str, client: str, name: str) -> list[dict]:
        now = time.time()
        with self.cond:
            room = self.presence.setdefault(key, {})
            for cid in [c for c, v in room.items() if now - v["at"] > PRESENCE_TTL]:
                del room[cid]
            if client and (client in room or len(room) < MAX_VIEWERS):
                room[client] = {"name": name, "at": now}
            if len(self.presence) > MAX_WATCHED * 2:
                for k in [k for k, r in self.presence.items() if not r]:
                    del self.presence[k]
            return [{"id": c, "name": v["name"]} for c, v in room.items()]


def whoami(root: Path, headers) -> dict:
    tail = (headers.get("Tailscale-User-Login") or "").strip()
    if tail:
        return {"name": tail[:80], "source": "tailscale"}
    try:
        import prefs  # noqa: PLC0415
        name = (prefs.read(root / prefs.person_path()).get("name") or "").strip()
    except Exception:  # noqa: BLE001
        name = ""
    return {"name": name[:80], "source": "preferences"} if name else {"name": "", "source": "none"}


class Handler(SimpleHTTPRequestHandler):
    server_version = "AgateServe"
    sys_version = ""

    def __init__(self, *args, root: Path, **kwargs):
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def log_message(self, fmt, *args):  # quiet: the agent reads stdout
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ---------------- helpers
    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _rel(self) -> str:
        path = urllib.parse.urlsplit(self.path).path
        return urllib.parse.unquote(path).lstrip("/")

    def _allowed_static(self, rel: str) -> bool:
        if "\x00" in rel or "\\" in rel:
            return False
        parts = [p for p in rel.split("/") if p]
        if ".." in parts:
            return False
        norm = "/".join(parts) + ("/" if rel.endswith("/") or not parts else "")
        if not any(norm.startswith(p) or norm + "/" == p for p in STATIC_PREFIXES):
            return False
        inside_canvas = norm.startswith(".agate/core/canvas/")
        if any(p.startswith(".") for p in parts[3 if inside_canvas else 0:]):
            return False
        target = (self.root / norm).resolve()
        return target == self.root.resolve() or self.root.resolve() in target.parents

    # ---------------- GET
    def do_GET(self):
        rel = self._rel()
        if rel.startswith("api/"):
            return self._api_get(rel[4:])
        if rel in ("", "artifacts"):
            self.send_response(302)
            self.send_header("Location", "/artifacts/")
            self.end_headers()
            return None
        if not self._allowed_static(rel):
            self.send_error(403, "Not served by agate.py serve")
            return None
        return super().do_GET()

    def do_HEAD(self):
        if not self._allowed_static(self._rel()):
            self.send_error(403)
            return None
        return super().do_HEAD()

    def _api_get(self, route: str):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if route == "health":
            return self._json(200, {"ok": True, "comments": True, "live": True})
        if route == "whoami":
            return self._json(200, whoami(self.root, self.headers))
        if route == "events":
            return self._events((query.get("file") or [""])[0])
        if route == "comments":
            try:
                key, path = comments.store_path(self.root, (query.get("file") or [""])[0])
            except comments.CommentError as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(200, comments.load(path, key))
        return self._json(404, {"error": "unknown endpoint"})

    def _events(self, file: str):
        """Server-Sent Events for one artifact: {type: changed|edit, path, lines?, actor?}."""
        hub = getattr(self.server, "hub", None)
        if hub is None:
            return self._json(404, {"error": "live view off"})
        try:
            key, _ = comments.store_path(self.root, file)
        except comments.CommentError as exc:
            return self._json(400, {"error": str(exc)})
        if not hub.subscribe(key):
            return self._json(503, {"error": "too many live viewers"})
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last = hub.seq
            self.wfile.write(b"retry: 3000\n: connected\n\n")
            self.wfile.flush()
            while not getattr(self.server, "_agate_closing", False):
                batch = hub.wait(last, HEARTBEAT_SECONDS)
                if not batch:
                    self.wfile.write(b": ping\n\n")
                for n, event in batch:
                    last = n
                    if belongs(key, event.get("path", "")):
                        data = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"id: {n}\ndata: {data}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            hub.unsubscribe(key)
        return None

    # ---------------- POST
    def do_POST(self):
        rel = self._rel()
        if not rel.startswith("api/"):
            return self._json(405, {"error": "read-only"})
        if self.headers.get(API_HEADER) != "1":
            return self._json(403, {"error": f"missing {API_HEADER} header"})
        origin = self.headers.get("Origin")
        if origin:
            o = urllib.parse.urlsplit(origin)
            if o.netloc != self.headers.get("Host", ""):
                return self._json(403, {"error": "cross-origin request refused"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "bad length"})
        if length > MAX_BODY:
            return self._json(413, {"error": f"body too large (max {MAX_BODY} bytes)"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "invalid JSON"})
        author = whoami(self.root, self.headers)["name"] or body.get("author")
        route = rel[4:]
        hub = getattr(self.server, "hub", None)
        if route == "events" and hub is not None:
            path = str(body.get("path") or "").replace("\\", "/").lstrip("/")
            parts = [p for p in path.split("/") if p]
            if not parts or parts[0] != "artifacts" or ".." in parts:
                return self._json(400, {"error": "path must be inside artifacts/"})
            event = {"type": "edit", "path": "/".join(parts)}
            lines = str(body.get("lines") or "")
            if re.fullmatch(r"\d{1,7}(-\d{1,7})?", lines):
                event["lines"] = lines
            actor = str(body.get("actor") or "AI").strip()[:40]
            event["actor"] = actor or "AI"
            return self._json(202, {"seq": hub.publish(event)})
        if route == "presence" and hub is not None:
            try:
                key, _ = comments.store_path(self.root, body.get("file", ""))
            except comments.CommentError as exc:
                return self._json(400, {"error": str(exc)})
            client = re.sub(r"[^A-Za-z0-9_-]", "", str(body.get("id") or ""))[:32]
            name = (author or "").strip()[:40]
            return self._json(200, {"viewers": hub.touch_presence(key, client, name)})
        try:
            if route == "comments":
                return self._json(201, comments.add(self.root, body.get("file", ""), body.get("text"), author,
                                                    body.get("anchor")))
            if route == "comments/reply":
                return self._json(201, comments.reply(self.root, str(body.get("id", "")), body.get("text"), author,
                                                      body.get("file")))
            if route == "comments/resolve":
                return self._json(200, comments.resolve(self.root, str(body.get("id", "")),
                                                        bool(body.get("resolved", True)), author, body.get("file")))
        except comments.CommentError as exc:
            msg = str(exc)
            return self._json(413 if "too long" in msg or "too large" in msg else 400, {"error": msg})
        return self._json(404, {"error": "unknown endpoint"})

    def do_PUT(self):
        return self._json(405, {"error": "method not allowed"})

    do_DELETE = do_PUT


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("no free port")


def make_server(root: Path, port: int = DEFAULT_PORT, live: bool = True) -> ThreadingHTTPServer:
    """Always binds to 127.0.0.1 (there is no option to change it)."""
    root = Path(root).resolve()
    server = ThreadingHTTPServer((HOST, port), partial(Handler, root=root))
    server.daemon_threads = True
    server.hub = LiveHub(root) if live else None
    return server


def close_server(server) -> None:
    server._agate_closing = True
    hub = getattr(server, "hub", None)
    if hub is not None:
        hub.stop()
        with hub.cond:
            hub.cond.notify_all()
    server.server_close()


def _write_state(root: Path, port: int) -> None:
    path = root / SERVE_STATE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": port, "pid": os.getpid(), "started": time.time()}), encoding="utf-8")
    except OSError:
        pass


def _clear_state(root: Path) -> None:
    path = root / SERVE_STATE
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass


def cmd_serve(args) -> int:
    root = Path(args.root).resolve()
    if getattr(args, "action", None) == "notify":
        return cmd_notify(args)
    port = free_port(args.port)
    server = make_server(root, port)
    _write_state(root, port)
    print(f"Serving artifacts at http://{HOST}:{port}/artifacts/ (comments and live view on; Ctrl-C to stop).")
    print("Only this machine can open it. From another device: remote-preview skill or the Orca browser.")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        close_server(server)
        _clear_state(root)
    return 0


# ---------------------------------------------------------------- `serve notify` (called by harness hooks)

def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _line_hint(path: Path, snippet: str) -> str:
    """Line range where `snippet` now sits in the file ('' if unknown). Cheap: one read, one find."""
    if not snippet:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    at = text.find(snippet)
    if at < 0:
        return ""
    first = text.count("\n", 0, at) + 1
    last = first + snippet.count("\n")
    return f"{first}-{last}" if last > first else str(first)


def notify_from_hook(root: Path, raw: str) -> tuple[str, str]:
    """(file, lines) from a harness hook payload (Claude Code PostToolUse: tool_input.file_path, new_string…)."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return "", ""
    tool_input = (data or {}).get("tool_input") or {}
    file = str(tool_input.get("file_path") or tool_input.get("path") or "")
    snippet = tool_input.get("new_string") or ""
    if not snippet and isinstance(tool_input.get("edits"), list) and tool_input["edits"]:
        snippet = (tool_input["edits"][0] or {}).get("new_string") or ""
    lines = ""
    if file:
        target = Path(file) if os.path.isabs(file) else root / file
        lines = _line_hint(target, snippet) if snippet else ""
    return file, lines


def notify(root: Path, file: str, lines: str = "", actor: str = "AI") -> bool:
    """Tell the running viewer that `file` was just edited. Silent; False when nothing to notify."""
    if not file:
        return False
    target = (Path(file) if os.path.isabs(file) else root / file).resolve()
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return False
    if not rel.startswith("artifacts/"):
        return False
    try:
        state = json.loads((root / SERVE_STATE).read_text(encoding="utf-8"))
        port = int(state["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not _alive(state.get("pid")):
        return False
    body = json.dumps({"path": rel, "lines": lines, "actor": actor}).encode()
    req = urllib.request.Request(f"http://{HOST}:{port}/api/events", data=body, method="POST",
                                 headers={"Content-Type": "application/json", API_HEADER: "1"})
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return 200 <= resp.status < 300
    except OSError:
        return False


def cmd_notify(args) -> int:
    """Always exits 0 and prints nothing: it runs inside harness hooks and must cost no tokens."""
    root = Path(args.root).resolve()
    try:
        if args.from_hook:
            file, lines = notify_from_hook(root, sys.stdin.read())
        else:
            file, lines = args.file or "", args.lines or ""
        notify(root, file, lines, (args.actor or "AI"))
    except Exception:  # noqa: BLE001 - a hook must never fail the harness
        pass
    return 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("serve", help="view artifacts and canvases locally (127.0.0.1) with comments and live view; "
                                     "`serve notify` tells it about an edit (for harness hooks)")
    p.add_argument("action", nargs="?", choices=("notify",), help="notify: report an edit to the running viewer")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"preferred port (default {DEFAULT_PORT}; "
                   "another free one if busy)")
    p.add_argument("--file", help="notify: edited file (inside artifacts/)")
    p.add_argument("--lines", help="notify: line range, e.g. 12-30")
    p.add_argument("--actor", default="AI", help="notify: who edited (default AI)")
    p.add_argument("--from-hook", action="store_true", help="notify: read the harness hook JSON from stdin")
    p.set_defaults(func=cmd_serve)
