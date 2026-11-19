"""`agate.py tokens`: how much context the project takes, per model family, and when to trim or index.

Groups: what is loaded in every message (AGENTS.md, CLAUDE.md, output styles, skill descriptions, memory index),
shared memory, the corpus (documents/ + artifacts/) and the heaviest files.

Counts, per provider (never averaged across providers: each tokenizer is exact only for its own models):
- estimate: characters / 3.5, adjusted by that provider's calibration factor once an exact count has run;
- exact (`--exact`): Claude via the count_tokens API (API key or `ant` login), Gemini via countTokens
  (GEMINI_API_KEY), OpenAI via tiktoken if installed. Failures fall back to the estimate silently.
Thresholds come from `.agate/config.yml` and turn into recommendations (trim, condense, index, RAG, split).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CHARS_PER_TOKEN = 3.5
PROVIDERS = ("claude", "gemini", "openai")
CALIBRATION = Path("memory/local/token-calibration.json")
REAL_CACHE = Path("memory/local/token-real.json")
MCP_CACHE = Path("memory/local/mcp-tools.json")
REAL_REFRESH = _dt.timedelta(days=7)
STATE = Path("memory/local/state.json")
CHECK_EVERY = _dt.timedelta(days=7)
CLAUDE_MODEL = "claude-opus-5-5"
GEMINI_MODEL = os.environ.get("AGATE_GEMINI_MODEL", "gemini-2.5-flash")
CHUNK_CHARS = 400_000
TEXT_SUFFIXES = {".md", ".txt", ".html", ".htm", ".json", ".csv", ".tsv", ".yml", ".yaml", ".xml", ".py", ".js",
                 ".ts", ".css", ".svg", ".toml", ".ini", ".rst", ".org", ".tex", ".sql", ".sh", ".mjs", ".cjs"}
DEFAULTS = {
    "tokens_always_loaded_warn": 3000,
    "tokens_memory_index_lines": 150,
    "tokens_shared_memory_warn": 30000,
    "tokens_corpus_index": 100000,
    "tokens_corpus_rag": 300000,
    "tokens_file_large": 20000,
    "tokens_skill_descriptions_warn": 1500,
    "tokens_first_turn_warn": 30000,
    "tokens_mcp_tools_warn": 8000,
}
ERRORS = {"skipped": []}


# ---------------------------------------------------------------- reading text

def read_text(path: Path) -> str | None:
    """Text of a file, or None if it is binary / unreadable. PDFs through pdftotext when available."""
    if path.suffix.lower() == ".pdf":
        exe = shutil.which("pdftotext")
        if not exe:
            ERRORS["skipped"].append(f"{path.name}: PDF skipped (pdftotext not installed)")
            return None
        try:
            return subprocess.run([exe, "-layout", str(path), "-"], capture_output=True, text=True,
                                  timeout=120, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            ERRORS["skipped"].append(f"{path.name}: PDF could not be read")
            return None
    if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def files_under(root: Path, rel: str) -> list[Path]:
    base = root / rel
    if base.is_file():
        return [base]
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.is_file() and not any(part.startswith(".") for part in
                                                                         p.relative_to(root).parts))


def skill_frontmatters(root: Path) -> list[tuple[str, str]]:
    """(skill name, frontmatter) of every installed skill: what harnesses load into every message."""
    out = []
    for skill in sorted((root / ".agents/skills").glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if m:
            out.append((skill.parent.name, m.group(1)))
    return out


def skill_descriptions(root: Path) -> str:
    return "\n".join(fm for _, fm in skill_frontmatters(root))


def collect(root: Path, paths: list[str] | None = None, only_always: bool = False) -> dict[str, list[tuple[str, str]]]:
    """group → [(label, text)]."""
    if paths:
        group = []
        for rel in paths:
            for f in files_under(root, rel):
                text = read_text(f)
                if text is not None:
                    group.append((f.relative_to(root).as_posix(), text))
        return {"paths": group}
    always = []
    for rel in ("AGENTS.md", "CLAUDE.md", "memory/INDEX.md"):
        f = root / rel
        if f.is_file():
            always.append((rel, f.read_text(encoding="utf-8")))
    for f in sorted((root / ".claude/output-styles").glob("*.md")):
        always.append((f.relative_to(root).as_posix(), f.read_text(encoding="utf-8")))
    desc = skill_descriptions(root)
    if desc:
        always.append(("skill descriptions", desc))
    if only_always:
        return {"always_loaded": always}
    shared = [(f.relative_to(root).as_posix(), t) for f in files_under(root, "memory/shared")
              if (t := read_text(f)) is not None]
    corpus = [(f.relative_to(root).as_posix(), t) for rel in ("documents", "artifacts")
              for f in files_under(root, rel) if (t := read_text(f)) is not None]
    return {"always_loaded": always, "shared_memory": shared, "corpus": corpus}


# ---------------------------------------------------------------- counting

def estimate(text: str) -> int:
    return int(round(len(text) / CHARS_PER_TOKEN))


def load_calibration(root: Path) -> dict:
    path = root / CALIBRATION
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        return {}


def save_calibration(root: Path, provider: str, factor: float) -> None:
    data = load_calibration(root)
    data[provider] = {"factor": round(factor, 4), "date": _dt.date.today().isoformat()}
    path = root / CALIBRATION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _post_json(url: str, body: dict, headers: dict, timeout: float = 30.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _secret(root: Path, name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        import env  # noqa: PLC0415
        return env.values(root).get(name, "").strip()
    except Exception:  # noqa: BLE001
        return ""


def claude_headers(root: Path) -> dict | None:
    key = _secret(root, "ANTHROPIC_API_KEY")
    if key:
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if shutil.which("ant"):
        try:
            token = subprocess.run(["ant", "auth", "print-credentials", "--access-token"], capture_output=True,
                                   text=True, timeout=20, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            token = ""
        if token:
            return {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20",
                    "anthropic-version": "2023-06-01"}
    return None


def _chunks(text: str):
    for i in range(0, len(text), CHUNK_CHARS):
        yield text[i:i + CHUNK_CHARS]


def exact_claude(root: Path, text: str, headers: dict | None = None) -> int | None:
    headers = headers or claude_headers(root)
    if not headers or not text:
        return None if not headers else 0
    total = 0
    for part in _chunks(text):
        status, data = _post_json("https://api.anthropic.com/v1/messages/count_tokens",
                                  {"model": CLAUDE_MODEL, "messages": [{"role": "user", "content": part}]}, headers)
        if status != 200 or "input_tokens" not in data:
            return None
        total += int(data["input_tokens"])
    return total


def exact_gemini(root: Path, text: str) -> int | None:
    key = _secret(root, "GEMINI_API_KEY")
    if not key or not text:
        return None if not key else 0
    total = 0
    for part in _chunks(text):
        status, data = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:countTokens",
            {"contents": [{"parts": [{"text": part}]}]}, {"x-goog-api-key": key})
        if status != 200 or "totalTokens" not in data:
            return None
        total += int(data["totalTokens"])
    return total


def exact_openai(_root: Path, text: str) -> int | None:
    try:
        import tiktoken  # noqa: PLC0415
    except ImportError:
        return None
    return len(tiktoken.get_encoding("o200k_base").encode(text))


EXACT = {"claude": exact_claude, "gemini": exact_gemini, "openai": exact_openai}


def measure(root: Path, groups: dict, providers: list[str], exact: bool) -> dict:
    """{group: {provider: {"tokens", "source"}}, "_files": [...]} — one row per provider, never averaged."""
    calib = load_calibration(root)
    report: dict = {"groups": {}, "files": [], "notes": []}
    exact_done: dict[str, tuple[int, int]] = {}  # provider → (exact total, raw estimate total)
    for group, items in groups.items():
        text = "\n".join(t for _, t in items)
        raw = estimate(text)
        rows = {}
        for prov in providers:
            factor = calib.get(prov, {}).get("factor")
            row = {"tokens": int(round(raw * factor)) if factor else raw,
                   "source": f"calibrated {calib[prov]['date']}, ±5%" if factor else "estimate, ±15%"}
            if exact:
                try:
                    value = EXACT[prov](root, text)
                except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                    value = None
                if value is not None:
                    row = {"tokens": value, "source": "exact"}
                    got, est = exact_done.get(prov, (0, 0))
                    exact_done[prov] = (got + value, est + raw)
                else:
                    report["notes"].append(f"{prov}: exact count unavailable for {group}; using the estimate")
            rows[prov] = row
        report["groups"][group] = rows
        for label, t in items:
            report["files"].append({"path": label, "group": group, "tokens": estimate(t)})
    for prov, (got, est) in exact_done.items():
        if est > 0 and got > 0:
            save_calibration(root, prov, got / est)
    skills = skill_frontmatters(root)
    if skills and "always_loaded" in groups:
        raw = estimate("\n".join(fm for _, fm in skills))
        factor = calib.get("claude", {}).get("factor") or 1
        report["skill_descriptions"] = {"skills": len(skills), "tokens": int(round(raw * factor))}
    index = root / "memory/INDEX.md"
    if "always_loaded" in groups and index.is_file():
        factor = calib.get("claude", {}).get("factor") or 1
        report["memory_index"] = {"lines": len(index.read_text(encoding="utf-8").splitlines()),
                                  "tokens": int(round(estimate(index.read_text(encoding="utf-8")) * factor))}
    report["files"].sort(key=lambda f: f["tokens"], reverse=True)
    report["files"] = [f for f in report["files"] if f["path"] != "skill descriptions"][:10]
    report["notes"] += ERRORS["skipped"]
    ERRORS["skipped"] = []
    return report


# ---------------------------------------------------------------- recommendations

def thresholds(root: Path) -> dict:
    out = dict(DEFAULTS)
    try:
        import config  # noqa: PLC0415
        cfg = config.read_config(root)
        out.update({k: cfg[k] for k in DEFAULTS if isinstance(cfg.get(k), (int, float))})
    except Exception:  # noqa: BLE001
        pass
    return out


def top(rows: dict) -> int:
    """Highest count among the providers in use: warn as soon as any model the team uses crosses a limit."""
    return max((r["tokens"] for r in rows.values()), default=0)


def recommendations(root: Path, report: dict, include_index: bool = True) -> list[str]:
    th = thresholds(root)
    g = report["groups"]
    recs = []
    if "always_loaded" in g and top(g["always_loaded"]) > th["tokens_always_loaded_warn"]:
        recs.append(f"always-loaded ≈{top(g['always_loaded']):,} tokens (> {th['tokens_always_loaded_warn']:,}): "
                    "trim the instructions or move procedures to guides")
    if include_index:
        index = root / "memory/INDEX.md"
        n = len(index.read_text(encoding="utf-8").splitlines()) if index.is_file() else 0
        if n > th["tokens_memory_index_lines"]:
            recs.append(f"memory/INDEX.md has {n} lines (> {th['tokens_memory_index_lines']}): condense it")
    if "shared_memory" in g and top(g["shared_memory"]) > th["tokens_shared_memory_warn"]:
        recs.append(f"shared memory ≈{top(g['shared_memory']):,} tokens (> {th['tokens_shared_memory_warn']:,}): "
                    "condense or archive old entries")
    if "corpus" in g:
        c = top(g["corpus"])
        if c > th["tokens_corpus_rag"]:
            recs.append(f"corpus ≈{c:,} tokens (> {th['tokens_corpus_rag']:,}): consider RAG / semantic search")
        elif c > th["tokens_corpus_index"]:
            recs.append(f"corpus ≈{c:,} tokens (> {th['tokens_corpus_index']:,}): consider a search index")
    sd = report.get("skill_descriptions")
    if sd and sd["tokens"] > th["tokens_skill_descriptions_warn"]:
        recs.append(f"skill descriptions ≈{sd['tokens']:,} tokens across {sd['skills']} skills "
                    f"(> {th['tokens_skill_descriptions_warn']:,}): remove the ones not used "
                    "(`python3 .agate/agate.py remove <name>`)")
    big = [f for f in report["files"] if f["tokens"] > th["tokens_file_large"]]
    if big:
        names = ", ".join(f"{f['path']} (≈{f['tokens']:,})" for f in big[:3])
        recs.append(f"large files: {names}: summarize or split them")
    return recs


def weekly_line(root: Path) -> list[str]:
    """For `agate.py start`: at most once a week, offline estimate only, ≤1 line and only if a threshold is crossed."""
    if os.environ.get("AGATE_OFFLINE_TOKENS"):
        return []
    import start  # noqa: PLC0415
    path = root / STATE
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError:
        state = {}
    current = start.now()
    last = state.get("last_tokens_check")
    if last:
        try:
            if current - _dt.datetime.fromisoformat(last) < CHECK_EVERY:
                return []
        except ValueError:
            pass
    report = measure(root, collect(root), ["claude"], exact=False)
    recs = recommendations(root, report, include_index=False)
    state["last_tokens_check"] = current.isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if not recs:
        return []
    return ["Context budget: " + "; ".join(recs) + ". Details: `python3 .agate/agate.py tokens`."]


# ---------------------------------------------------------------- what really enters the first turn

def first_turn_tokens(path: Path) -> int | None:
    """Input tokens of the first main-thread assistant turn of a Claude Code .jsonl (usage only, never content)."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "assistant" or d.get("isSidechain"):
                    continue
                u = (d.get("message") or {}).get("usage") or {}
                if not isinstance(u, dict) or "input_tokens" not in u:
                    continue
                return int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + \
                    int(u.get("cache_read_input_tokens") or 0)
    except OSError:
        return None
    return None


def session_files(root: Path) -> list[Path]:
    """Claude Code transcripts of this repo (Orca's Claude sessions are the same files)."""
    try:
        import chats  # noqa: PLC0415
        repo = chats.Repo(chats.find_root(root))
        found = chats.Found()
        chats.scan_claude(repo, found)
    except Exception:  # noqa: BLE001 — formats of other tools may change; never break tokens
        return []
    paths = {Path(r["path"]) for c in found.chats for r in c["refs"]
             if r.get("harness") == "claude-code" and r.get("path")}
    return sorted((p for p in paths if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)


def median(values: list[int]) -> int:
    v = sorted(values)
    if not v:
        return 0
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else int(round((v[mid - 1] + v[mid]) / 2))


def measure_real(root: Path, sessions: int = 5) -> dict:
    """First-turn input of the last N sessions of this repo → cached in memory/local/token-real.json."""
    values = []
    for p in session_files(root):
        n = first_turn_tokens(p)
        if n:
            values.append({"session": p.stem[:8], "date": _dt.datetime.fromtimestamp(p.stat().st_mtime)
                           .isoformat(timespec="seconds"), "first_turn": n})
        if len(values) >= sessions:
            break
    agate = measure(root, collect(root, only_always=True), ["claude"], exact=False)
    always = agate["groups"]["always_loaded"]["claude"]["tokens"]
    result = {"measured": _dt.datetime.now().isoformat(timespec="seconds"), "harness": "claude-code",
              "sessions": values, "median": median([v["first_turn"] for v in values]),
              "last": values[0]["first_turn"] if values else 0, "agate_always_loaded": always,
              "memory_index": (agate.get("memory_index") or {}).get("tokens", 0)}
    _write_json(root / REAL_CACHE, result)
    return result


def measure_mcp(root: Path, timeout: float = 30.0) -> dict:
    """Tool-definition weight of each local connector (MCP tools/list) → cached in memory/local/mcp-tools.json."""
    rows = {}
    try:
        import mcp  # noqa: PLC0415
        names = list(mcp.load_servers(root))
        for name in names:
            r = mcp.tools_list_size(root, name, timeout)
            if r.get("ok"):
                rows[name] = {"tools": r["tools"], "tokens": int(round(r["bytes"] / CHARS_PER_TOKEN))}
            else:
                rows[name] = {"skipped": r.get("reason", "unavailable")}
    except Exception as exc:  # noqa: BLE001
        rows["_error"] = {"skipped": str(exc)[:120]}
    result = {"measured": _dt.datetime.now().isoformat(timespec="seconds"), "servers": rows,
              "total": sum(r.get("tokens", 0) for r in rows.values())}
    _write_json(root / MCP_CACHE, result)
    return result


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def k(n: int) -> str:
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def real_lines(r: dict, n_requested: int) -> list[str]:
    if not r.get("sessions"):
        return ["first turn: no Claude Code sessions found for this repo yet"]
    med, always = r["median"], r["agate_always_loaded"]
    pct = f" ({round(100 * always / med)}%)" if med else ""
    return [f"first turn (claude-code, last {len(r['sessions'])} sessions): median {k(med)} tokens · last "
            f"{k(r['last'])} · Agate always-loaded ≈{k(always)}{pct} · rest (harness prompt, tools, other) "
            f"≈{k(max(med - always, 0))}"]


def mcp_lines(m: dict) -> list[str]:
    rows = m.get("servers") or {}
    if not rows:
        return ["MCP tools: no connectors in .agate/mcp/servers.json"]
    out = []
    for name, r in rows.items():
        out.append(f"  {name}: {r['tools']} tools ≈{k(r['tokens'])} tokens" if "tokens" in r
                   else f"  {name}: skipped ({r['skipped']})")
    return [f"MCP tools: ≈{k(m.get('total', 0))} tokens"] + out


def attention(root: Path) -> list[dict]:
    """For `agate.py start`: ≤1 line from caches, only above the thresholds. Never raises, never scans MCP."""
    try:
        if os.environ.get("AGATE_OFFLINE_TOKENS"):
            return []
        th = thresholds(root)
        real = _read_json(root / REAL_CACHE)
        stale = True
        if real.get("measured"):
            try:
                stale = _dt.datetime.now() - _dt.datetime.fromisoformat(real["measured"]) > REAL_REFRESH
            except ValueError:
                stale = True
        if stale:  # cheap: only the head of a few transcripts
            real = measure_real(root)
        mcp_data = _read_json(root / MCP_CACHE)
        mcp_total = int(mcp_data.get("total") or 0)
        first = int(real.get("last") or real.get("median") or 0)
        if first <= th["tokens_first_turn_warn"] and mcp_total <= th["tokens_mcp_tools_warn"]:
            return []
        parts = {"MCP tool definitions": (mcp_total, "disable unused connectors in .agate/mcp/servers.json"),
                 "memory/INDEX.md": (int(real.get("memory_index") or 0), "condense memory/INDEX.md"),
                 "Agate always-loaded": (int(real.get("agate_always_loaded") or 0),
                                         "move procedures from AGENTS.md to guides")}
        name, (size, action) = max(parts.items(), key=lambda kv: kv[1][0])
        if first > th["tokens_first_turn_warn"]:
            head = f"first turn ≈{k(first)} tokens (> {k(th['tokens_first_turn_warn'])})"
        else:
            head = f"MCP tool definitions ≈{k(mcp_total)} tokens (> {k(th['tokens_mcp_tools_warn'])})"
        return [{"severity": 6, "text": f"{head}; biggest Agate-side part: {name} ≈{k(size)} → {action} "
                                        "(details: `python3 .agate/agate.py tokens --real --mcp`)"}]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- live validators for `agate.py env check --live`

def _validate_anthropic(value: str, timeout: float):
    status, _ = _post_json("https://api.anthropic.com/v1/messages/count_tokens",
                           {"model": CLAUDE_MODEL, "messages": [{"role": "user", "content": "ok"}]},
                           {"x-api-key": value, "anthropic-version": "2023-06-01"}, timeout)
    return ("ok", None) if status == 200 else ("rejected", status)


def _validate_gemini(value: str, timeout: float):
    status, _ = _post_json(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:countTokens",
                           {"contents": [{"parts": [{"text": "ok"}]}]}, {"x-goog-api-key": value}, timeout)
    return ("ok", None) if status == 200 else ("rejected", status)


def _safe(fn):
    def run(value: str, timeout: float):
        try:
            return fn(value, timeout)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return ("error", None)
    return run


ENV_VALIDATORS = {"ANTHROPIC_API_KEY": _safe(_validate_anthropic), "GEMINI_API_KEY": _safe(_validate_gemini)}


# ---------------------------------------------------------------- CLI

LABELS = {"always_loaded": "always loaded", "shared_memory": "shared memory", "corpus": "corpus (documents + "
          "artifacts)", "paths": "selected paths"}


def format_rows(rows: dict) -> str:
    """One cell per provider; a single row when every provider is the same uncalibrated estimate."""
    values = {r["tokens"] for r in rows.values()}
    if len(rows) > 1 and len(values) == 1 and all(r["source"].startswith("estimate") for r in rows.values()):
        r = next(iter(rows.values()))
        return f"≈{r['tokens']:,} (estimate (all models), ±15%)"
    return " · ".join(f"{p} {('≈' if r['source'] != 'exact' else '')}{r['tokens']:,} ({r['source']})"
                      for p, r in rows.items())


def cmd_tokens(a) -> int:
    root = Path(a.root).resolve()
    if a.real or a.mcp:
        out = {}
        if a.real:
            out["real"] = measure_real(root, a.sessions)
        if a.mcp:
            out["mcp"] = measure_mcp(root)
        if a.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        if "real" in out:
            print("\n".join(real_lines(out["real"], a.sessions)))
            if out["real"].get("memory_index"):
                print(f"  of which memory/INDEX.md: ≈{k(out['real']['memory_index'])}")
        if "mcp" in out:
            print("\n".join(mcp_lines(out["mcp"])))
        return 0
    providers = list(PROVIDERS) if a.provider == "all" else [a.provider]
    report = measure(root, collect(root, a.paths or None), providers, a.exact)
    report["recommendations"] = recommendations(root, report) if not a.paths else []
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for group, rows in report["groups"].items():
        print(f"{LABELS.get(group, group)}: {format_rows(rows)}")
        if group == "always_loaded" and report.get("skill_descriptions"):
            sd = report["skill_descriptions"]
            print(f"  of which skill descriptions: ≈{sd['tokens']:,} ({sd['skills']} skills)")
        if group == "always_loaded" and report.get("memory_index"):
            mi = report["memory_index"]
            print(f"  of which memory/INDEX.md: ≈{mi['tokens']:,} ({mi['lines']} lines)")
    if report["files"]:
        print("heaviest files: " + ", ".join(f"{f['path']} ≈{f['tokens']:,}" for f in report["files"][:5]))
    for note in report["notes"]:
        print("note: " + note)
    print("recommendations: " + ("; ".join(report["recommendations"]) if report["recommendations"] else "none"))
    return 0


def register(sub, root: Path) -> None:
    p = sub.add_parser("tokens", help="context the project takes, per model family, with recommendations")
    p.add_argument("paths", nargs="*", help="count only these files/folders")
    p.add_argument("--exact", action="store_true", help="use the providers' official counters when credentials exist")
    p.add_argument("--provider", choices=(*PROVIDERS, "all"), default="all")
    p.add_argument("--real", action="store_true",
                   help="what really entered the first turn of the last sessions (harness transcripts, usage only)")
    p.add_argument("--mcp", action="store_true", help="weight of each local connector's tool definitions (tools/list)")
    p.add_argument("--sessions", type=int, default=5, help="how many recent sessions --real looks at")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_tokens)
