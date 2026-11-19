"""`agate.py serve`: view artifacts and canvases locally, with comments.

A static server for artifacts/, documents/ and the canvas engine, bound to 127.0.0.1 only, plus a small JSON API
for comments (stored by comments.py next to each artifact). Nothing else in the project is served: never .env,
.git, memory/ or the rest of .agate/.

To open it from another device, use a private channel (the remote-preview skill with its allowlist, or the Orca
browser). This server never binds to other interfaces.
"""
from __future__ import annotations

import json
import socket
import sys
import urllib.parse
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
            return self._json(200, {"ok": True, "comments": True})
        if route == "whoami":
            return self._json(200, whoami(self.root, self.headers))
        if route == "comments":
            try:
                key, path = comments.store_path(self.root, (query.get("file") or [""])[0])
            except comments.CommentError as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(200, comments.load(path, key))
        return self._json(404, {"error": "unknown endpoint"})

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


def make_server(root: Path, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Always binds to 127.0.0.1 (there is no option to change it)."""
    return ThreadingHTTPServer((HOST, port), partial(Handler, root=Path(root).resolve()))


def cmd_serve(args) -> int:
    root = Path(args.root).resolve()
    port = free_port(args.port)
    server = make_server(root, port)
    print(f"Serving artifacts at http://{HOST}:{port}/artifacts/ (comments on; Ctrl-C to stop).")
    print("Only this machine can open it. From another device: remote-preview skill or the Orca browser.")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("serve", help="view artifacts and canvases locally (127.0.0.1) with comments")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"preferred port (default {DEFAULT_PORT}; "
                   "another free one if busy)")
    p.set_defaults(func=cmd_serve)
