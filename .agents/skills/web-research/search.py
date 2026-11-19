#!/usr/bin/env python3
"""Web search with external engines (Exa, Tavily) for the web-research skill.

Usage:
  search.py keys
  search.py search --engine exa|tavily --query "..." [--depth basic|advanced] [--max N]
                   [--domains a.com,b.com] [--since YYYY-MM-DD]
  search.py extract --engine exa|tavily URL [URL ...] [--max-chars N]
  search.py verify URL [--expect "text"]

Keys are read from environment variables or from the .env at the repo root. They are never printed.
Uses only the Python standard library.
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request

TIMEOUT = 30
USER_AGENT = "Mozilla/5.0 (compatible; agate-web-research/0.1)"
KEY_NAMES = {"exa": "EXA_API_KEY", "tavily": "TAVILY_API_KEY"}
KEY_HELP = {
    "exa": "register it with `python3 .agate/agate.py env add EXA_API_KEY --where \"exa.ai → Dashboard → API keys\" "
           "--for web-research` (free plan available), then the person sets it with `agate.py env set EXA_API_KEY`",
    "tavily": "register it with `python3 .agate/agate.py env add TAVILY_API_KEY --where \"tavily.com → API keys\" "
              "--for web-research` (1,000 free credits per month), then `agate.py env set TAVILY_API_KEY`",
}


# ---------------------------------------------------------------- keys

def find_repo_root(start):
    cur = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(cur, ".git")) or os.path.exists(os.path.join(cur, "AGENTS.md")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def read_dotenv(root):
    values = {}
    if not root:
        return values
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            if name.startswith("export "):
                name = name[len("export "):].strip()
            value = value.strip().strip('"').strip("'")
            values[name] = value
    return values


def get_key(engine):
    name = KEY_NAMES[engine]
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return read_dotenv(find_repo_root(os.getcwd())).get(name, "").strip()


def require_key(engine):
    key = get_key(engine)
    if not key:
        fail(f"Missing {engine.capitalize()} key ({KEY_NAMES[engine]} in .env): {KEY_HELP[engine]}.", code=2)
    return key


# ---------------------------------------------------------------- helpers

def fail(message, code=1):
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


def out(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def post_json(url, body, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        fail(f"The engine returned error {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        fail(f"Could not connect to the engine: {exc.reason}")
    except TimeoutError:
        fail(f"The engine did not respond within {TIMEOUT} s.")


def strip_tags(text):
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def truncate(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def split_domains(value):
    return [d.strip() for d in value.split(",") if d.strip()] if value else []


# ---------------------------------------------------------------- Exa

def exa_search(args):
    key = require_key("exa")
    body = {
        "query": args.query,
        "numResults": args.max,
        "type": "deep" if args.depth == "deep" else "auto",
        "contents": {"highlights": {"numSentences": 3}} if args.depth == "basic" else {"text": {"maxCharacters": 2000}},
    }
    if args.domains:
        body["includeDomains"] = split_domains(args.domains)
    if args.since:
        body["startPublishedDate"] = f"{args.since}T00:00:00.000Z"
    data = post_json("https://api.exa.ai/search", body, {"x-api-key": key})
    results = []
    for r in data.get("results", []):
        snippet = " ".join(r.get("highlights") or []) or r.get("text") or r.get("summary") or ""
        results.append({
            "title": r.get("title"),
            "url": r.get("url"),
            "published": r.get("publishedDate"),
            "snippet": truncate(snippet, 1200),
        })
    payload = {"engine": "exa", "query": args.query, "results": results}
    if "costDollars" in data:
        payload["cost"] = data["costDollars"]
    return payload


def exa_extract(args):
    key = require_key("exa")
    data = post_json("https://api.exa.ai/contents",
                     {"urls": args.urls, "text": {"maxCharacters": args.max_chars}},
                     {"x-api-key": key})
    payload = {"engine": "exa", "results": [
        {"url": r.get("url"), "title": r.get("title"), "text": truncate(r.get("text"), args.max_chars)}
        for r in data.get("results", [])
    ]}
    if "costDollars" in data:
        payload["cost"] = data["costDollars"]
    return payload


# ---------------------------------------------------------------- Tavily

def tavily_search(args):
    key = require_key("tavily")
    body = {
        "query": args.query,
        "search_depth": "advanced" if args.depth in ("advanced", "deep") else "basic",
        "max_results": args.max,
        "include_usage": True,
    }
    if args.domains:
        body["include_domains"] = split_domains(args.domains)
    if args.since:
        body["start_date"] = args.since
    data = post_json("https://api.tavily.com/search", body, {"Authorization": f"Bearer {key}"})
    results = [{
        "title": r.get("title"),
        "url": r.get("url"),
        "published": r.get("published_date"),
        "snippet": truncate(r.get("content"), 1200),
    } for r in data.get("results", [])]
    payload = {"engine": "tavily", "query": args.query, "results": results}
    if "usage" in data:
        payload["usage"] = data["usage"]
    return payload


def tavily_extract(args):
    key = require_key("tavily")
    data = post_json("https://api.tavily.com/extract",
                     {"urls": args.urls, "include_usage": True},
                     {"Authorization": f"Bearer {key}"})
    payload = {"engine": "tavily", "results": [
        {"url": r.get("url"), "text": truncate(r.get("raw_content"), args.max_chars)}
        for r in data.get("results", [])
    ]}
    if data.get("failed_results"):
        payload["failed"] = data["failed_results"]
    if "usage" in data:
        payload["usage"] = data["usage"]
    return payload


# ---------------------------------------------------------------- commands

def cmd_keys(_args):
    out({engine: bool(get_key(engine)) for engine in KEY_NAMES})


def cmd_search(args):
    if not args.query.strip():
        fail("The query is empty.")
    out(exa_search(args) if args.engine == "exa" else tavily_search(args))


def cmd_extract(args):
    out(exa_extract(args) if args.engine == "exa" else tavily_extract(args))


def cmd_verify(args):
    req = urllib.request.Request(args.url, headers={"User-Agent": USER_AGENT})
    result = {"url": args.url, "ok": False, "status": None, "found": None}
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            result["status"] = resp.status
            raw = resp.read(3_000_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
            result["ok"] = 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        out(result)
        return
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        result["error"] = str(getattr(exc, "reason", exc))
        out(result)
        return
    if args.expect is not None:
        text = strip_tags(raw).casefold()
        expect = re.sub(r"\s+", " ", args.expect).strip().casefold()
        result["found"] = expect in text
    out(result)


def build_parser():
    p = argparse.ArgumentParser(description="Web search with Exa or Tavily (web-research skill).")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("keys", help="Which keys are configured (without showing them).").set_defaults(func=cmd_keys)

    s = sub.add_parser("search", help="Search the web.")
    s.add_argument("--engine", choices=["exa", "tavily"], required=True)
    s.add_argument("--query", required=True)
    s.add_argument("--depth", choices=["basic", "advanced", "deep"], default="basic",
                   help="deep is expensive (Exa deep / Tavily advanced): ask first.")
    s.add_argument("--max", type=int, default=10)
    s.add_argument("--domains", help="Comma-separated domains.")
    s.add_argument("--since", help="Only from this date on (YYYY-MM-DD).")
    s.set_defaults(func=cmd_search)

    e = sub.add_parser("extract", help="Read the full content of pages.")
    e.add_argument("--engine", choices=["exa", "tavily"], required=True)
    e.add_argument("urls", nargs="+")
    e.add_argument("--max-chars", type=int, default=8000)
    e.set_defaults(func=cmd_extract)

    v = sub.add_parser("verify", help="Check that a page exists and contains a text.")
    v.add_argument("url")
    v.add_argument("--expect")
    v.set_defaults(func=cmd_verify)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
