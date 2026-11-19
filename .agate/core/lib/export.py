#!/usr/bin/env python3
"""Export an HTML artifact to PDF or PNG with headless Chrome/Chromium/Edge. No Python dependencies.

Usage (from the repo root):
    python3 .agate/agate.py export pdf artifacts/2026-11/2026-11-19-report.html
    python3 .agate/agate.py export pdf <file.html> --out report.pdf --paper Letter --landscape
    python3 .agate/agate.py export png <file.html> --width 1440 --height 900
    python3 .agate/agate.py export png <file.html> --width 1440 --full      # full page

The file is served by a temporary local server (127.0.0.1) from the repo root, so relative paths load
(images, `../../../.agate/core/canvas/…`, `canvas.json`). It waits for fonts to load before printing.
Without --out, the result is written next to the HTML with the same base name (.pdf / .png).

Paper: if the page defines `@page { size: … }`, it is respected; otherwise A4. --paper/--landscape force it.
The browser can be set with the AGATE_BROWSER variable (path to the executable).
"""
from __future__ import annotations

import argparse
import functools
import glob
import http.server
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

CANDIDATES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
              "microsoft-edge", "microsoft-edge-stable", "brave-browser"]


def find_browser() -> str | None:
    env = os.environ.get("AGATE_BROWSER")
    if env:
        return env if Path(env).exists() or shutil.which(env) else None
    for name in CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            paths += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                      os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                      os.path.join(base, "Chromium", "Application", "chrome.exe")]
    paths += sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-*/chrome")), reverse=True)
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".git").exists() or (p / "AGENTS.md").exists():
            return p
    return start


# ---------------------------------------------------------------- temporary server with injection
class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the repo root; injects the paper style and height measurement into the target HTML."""

    target = ""
    head_start = ""
    head_end = ""

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == self.target and (self.head_start or self.head_end):
            fs = Path(self.translate_path(self.path))
            html = fs.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"<head[^>]*>", html, re.I)
            html = (html[: m.end()] + self.head_start + html[m.end():]) if m else self.head_start + html
            html = re.sub(r"</head>", self.head_end + "</head>", html, count=1, flags=re.I) \
                if re.search(r"</head>", html, re.I) else html + self.head_end
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()


def serve(root: Path, target_rel: str, head_start: str, head_end: str):
    handler = type("H", (Handler,), {"target": "/" + target_rel, "head_start": head_start, "head_end": head_end})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(handler, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/{quote(target_rel)}"


# ---------------------------------------------------------------- Chrome
def run_browser(browser: str, args: list[str], url: str, wait_ms: int, timeout: int = 120) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="agate-export-") as prof:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--hide-scrollbars", "--mute-audio", f"--user-data-dir={prof}",
               "--run-all-compositor-stages-before-draw", f"--virtual-time-budget={wait_ms}", *args, url]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# Waits for fonts and leaves the total height in the DOM (for --full).
MEASURE = ("<script>(function(){function m(){var d=document.documentElement,b=document.body;"
           "d.setAttribute('data-agate-h',Math.ceil(Math.max(d.scrollHeight,b?b.scrollHeight:0)));}"
           "addEventListener('load',function(){(document.fonts&&document.fonts.ready||Promise.resolve())"
           ".then(function(){setTimeout(m,50)})});})();</script>")


def export(kind: str, src: Path, out: Path | None, paper: str | None, landscape: bool,
           width: int, height: int, full: bool, wait_ms: int) -> Path:
    browser = find_browser()
    if not browser:
        raise SystemExit("Could not find Chrome, Chromium or Edge on this machine. Install Google Chrome (or set the "
                         "path with the AGATE_BROWSER variable) and try again.")
    src = src.resolve()
    if not src.is_file():
        raise SystemExit(f"File not found: {src}")
    root = find_root(src.parent)
    try:
        rel = src.relative_to(root).as_posix()
    except ValueError:
        root, rel = src.parent, src.name
    out = (out or src.with_suffix("." + kind)).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    head_start = head_end = ""
    if kind == "pdf":
        orient = " landscape" if landscape else ""
        if paper or landscape:  # forced: goes last and wins over the page
            head_end = f"<style>@page {{ size: {paper or 'A4'}{orient}; }}</style>"
        else:  # A4 by default, but the page can define its own @page
            head_start = "<style>@page { size: A4; }</style>"
        head_start += "<style>html{-webkit-print-color-adjust:exact;print-color-adjust:exact}</style>"
    else:
        head_end = MEASURE

    srv, url = serve(root, rel, head_start, head_end)
    try:
        if kind == "pdf":
            r = run_browser(browser, [f"--print-to-pdf={out}", "--no-pdf-header-footer",
                                      "--print-to-pdf-no-header"], url, wait_ms)
        else:
            h = height
            if full:
                dom = run_browser(browser, [f"--window-size={width},{height}", "--dump-dom"], url, wait_ms)
                m = re.search(r'data-agate-h="(\d+)"', dom.stdout or "")
                h = max(height, min(int(m.group(1)), 16000)) if m else height
            r = run_browser(browser, [f"--window-size={width},{h}", f"--screenshot={out}"], url, wait_ms)
    finally:
        srv.shutdown()
    if not out.exists() or out.stat().st_size == 0:
        raise SystemExit("The browser did not produce the file.\n" + (r.stderr or "")[-800:])
    return out


PASSTHROUGH = {"export": "export an HTML artifact to PDF or PNG"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export an HTML artifact to PDF or PNG with headless Chrome.")
    sub = ap.add_subparsers(dest="kind", required=True)
    p = sub.add_parser("pdf", help="HTML → PDF")
    p.add_argument("file")
    p.add_argument("--out")
    p.add_argument("--paper", choices=["A4", "Letter", "Legal", "A3", "A5"], help="force the paper size")
    p.add_argument("--landscape", action="store_true", help="landscape page")
    p.add_argument("--wait", type=int, default=5000, help="ms to wait for fonts and scripts (default 5000)")
    s = sub.add_parser("png", help="HTML → PNG (screenshot)")
    s.add_argument("file")
    s.add_argument("--out")
    s.add_argument("--width", type=int, default=1440)
    s.add_argument("--height", type=int, default=900)
    s.add_argument("--full", action="store_true", help="capture the full page, not just the viewport")
    s.add_argument("--wait", type=int, default=5000)
    a = ap.parse_args(argv)
    out = export(a.kind, Path(a.file), Path(a.out) if a.out else None,
                 getattr(a, "paper", None), getattr(a, "landscape", False),
                 getattr(a, "width", 1440), getattr(a, "height", 900), getattr(a, "full", False), a.wait)
    print(f"Done: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
