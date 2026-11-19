"""Live checks for `agate.py env check --live`: does each key work? Returns (status, http_code); never the value."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def _post(url: str, body: dict, headers: dict, timeout: float) -> int:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _check(url: str, body: dict, headers: dict, timeout: float):
    try:
        code = _post(url, body, headers, timeout)
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return ("error", None)
    return ("ok", None) if code == 200 else ("rejected", code)


def exa(value: str, timeout: float):
    # Smallest authenticated call: one result, no contents.
    return _check("https://api.exa.ai/search", {"query": "test", "numResults": 1}, {"x-api-key": value}, timeout)


def tavily(value: str, timeout: float):
    return _check("https://api.tavily.com/search", {"query": "test", "max_results": 1},
                  {"Authorization": f"Bearer {value}"}, timeout)


VALIDATORS = {"EXA_API_KEY": exa, "TAVILY_API_KEY": tavily}
