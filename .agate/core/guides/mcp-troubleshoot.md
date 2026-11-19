# A connector that does not work (MCP)

The tool is `python3 .agate/agate.py mcp`; the project's list is `.agate/mcp/servers.json`. Explain things to the person in their language and in plain words.

## When a registered connector does not answer

For example, someone asks "search the data warehouse", `dw` is in `servers.json`, but the tools are not there:

```
python3 .agate/agate.py mcp doctor dw
```

It checks, in order:
1. **Generated config** for the current harness (detected from its environment; `--harness X` to force it) and that
   it is not out of date.
2. **Token** present in `.env` (names only, never values).
3. **The server starts**: `agate.py mcp run dw --test` launches it and does an MCP `initialize` handshake (local), or checks
   that the URL answers (remote; a 401 on an OAuth server means "sign in from the harness").
4. Reminders: harnesses load MCP servers **when a chat starts** (open a new chat; in Claude Code `/mcp` can
   reconnect); Claude Code asks to **approve** project servers the first time; Codex only reads
   `.codex/config.toml` in trusted projects.
5. **Unknown harness** (Antigravity or any other that `mcp.py` doesn't know): see `mcp-extend.md`.

## How it reaches each harness

`agate.py mcp sync` generates, from `.agate/mcp/servers.json`:

| Harness | Project file | Notes |
|---|---|---|
| Claude Code | `.mcp.json` | Asks to approve project servers the first time. Remote with token: `headersHelper` |
| Gemini CLI | `.gemini/settings.json` | Remote with token: goes through `agate.py mcp run` (proxy) |
| OpenCode | `opencode.json` | V1 format (`mcp.<name>`) or V2 (`mcp.servers.<name>`) depending on the installed version. If the project uses `opencode.jsonc` (with comments) it doesn't edit it: it shows what to paste |
| Codex | `.codex/config.toml` | Only in projects marked as trusted. Writes a `# agate-mcp:begin/end` block and leaves the rest alone |
| Orca | — | Uses the configuration of the harness running in each chat |

On Windows, if `python3` doesn't exist, generate with `python3 .agate/agate.py mcp --python py sync`.

## Keeping configs up to date (automatic)

`agate.py mcp sync` is the only thing that generates configs; everything else just decides when to run it.

- **Always every harness.** `sync` generates the files for all supported harnesses, not only the ones installed on
  your machine. The output is the same for everyone, so the committed files don't change depending on who committed
  last. Detection of the current harness is only used by `doctor`.
- **Fingerprint.** `sync` stores a sha256 of `.agate/mcp/servers.json` (and of `.agate/project/mcp.py`, if any) in
  `.agate/mcp-generated.json`. `agate.py mcp check` says "MCP config out of date" when they no longer match, and
  `agate.py mcp sync --if-stale` regenerates only then (and prints nothing when there is nothing to do).
- **Git hooks** (`.agate/core/hooks/`, committed; POSIX sh, also Git Bash on Windows):
  - `post-merge`, `post-checkout` (branch switches) and `post-rewrite` run `sync --if-stale`, so a connector a
    teammate added reaches your configs after `git pull`. They never block.
  - `pre-commit`: if the commit changes `.agate/mcp/servers.json` (or the extension), it regenerates and adds the generated
    files to the same commit. It blocks only if generation fails, and says why.
  - Git does not enable committed hooks by itself: `python3 .agate/agate.py mcp hooks install` (once per clone) sets
    `core.hooksPath` to `.agate/core/hooks`. The agent does it at the start of a conversation if `check` says they are
    not active, and tells the person. `agate.py mcp hooks status` shows the state.
  - The hooks look for `python3`, then `python`, then `py -3`.
- **No harness-specific hook by default.** A Claude Code hook (for example a `PostToolUse` hook on edits to
  `.agate/mcp/servers.json`) would also work, but it couples the base to one harness and adds nothing the fingerprint and
  git hooks don't already cover. Add one in your own settings only if you want it.

## Not verified yet

- That Gemini, OpenCode and Codex resolve the relative path `.agate/agate.py mcp` from the project root (that's how we
  generate it; if it fails, use the absolute path on that machine and don't commit that file).
- The `mcp-remote` proxy (a community package) for remote-with-token servers in Gemini and OpenCode: test it against a
  real server before relying on it.
- That Codex's `http_headers_helper` accepts the command as a string (the documentation describes it as a "local
  command").
