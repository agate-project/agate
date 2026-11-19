# Unknown harness, project extension and system level (MCP)

The tool is `python3 .agate/agate.py mcp`; the project's list is `.agate/mcp/servers.json`. Explain things to the person in their language and in plain words.

## Project extension (`.agate/project/mcp.py`)

A project can extend the MCP tool without editing it (`.agate/core/` is replaced by `agate.py update`; `.agate/project/` never
is). If `.agate/project/mcp.py` exists, `mcp.py` loads it and calls its optional hooks at fixed points:

```python
# .agate/project/mcp.py: everything is optional. `mcp` (the base module) is available, e.g. mcp.SCRIPT_REL.
import json

class Antigravity:
    name = "antigravity"
    def detect(self):                      # is it the harness running now? (used by doctor)
        import os; return "ANTIGRAVITY" in os.environ
    def config_path(self, root):           # relative to the project, or absolute
        return ".antigravity/mcp.json"
    def render(self, servers):             # servers.json "servers" → its format, as text. No secrets:
        return json.dumps({"servers": {    # local servers go through `agate.py mcp run <name>`
            n: {"command": "python3", "args": [mcp.SCRIPT_REL, "run", n]} for n in servers}}, indent=2) + "\n"
    def merge(self, existing, rendered):   # keep others' entries; here we simply replace the file
        return rendered

HARNESSES = [Antigravity()]
def before_sync(servers): return servers   # adjust the list before generating
def after_sync(report): pass               # something extra afterwards
def doctor_checks(name): return []         # extra lines for `agate.py mcp doctor`
```

When you meet a harness `mcp.py` doesn't know, it reads that harness's official MCP docs, writes the adapter
here, runs `agate.py mcp sync`, tells the person what it did and suggests adding that harness to Agate.

**Safety.** The extension is code that runs on this machine, sometimes from a git hook right after `git pull`, so it
only runs once approved on each machine (`memory/local/approvals.json`):
- **Your own change** (uncommitted, or the last commit touching it is yours by `git config user.email`): approved
  automatically.
- **Someone else's change** (it arrived by a pull): it is **not run**. The hooks generate the built-in harnesses only
  and print one notice; `check` keeps reporting it. The agent shows the person `agate.py mcp extension review` (the diff
  since the last approved version) and runs `agate.py mcp extension approve` only with their ok, then `agate.py mcp sync`.
- `agate.py mcp extension status` shows the state. Nothing is checked per message: only when `mcp.py` runs.

## System level (all of someone's projects)

```
python3 .agate/agate.py mcp install <name> --scope user --harness claude|codex|gemini|opencode        # shows what would change
python3 .agate/agate.py mcp install <name> --scope user --harness claude|codex|gemini|opencode --yes  # applies it
```

It copies the script to `~/.config/agate/bin/mcp.py`, saves the connector in `~/.config/agate/servers.json`, leaves
an empty variable in `~/.config/agate/.env` and registers it in the harness. Restart the harness afterwards.

### By hand, in each harness

If you'd rather not use the tool (formats verified on 2026-11-19 against the official documentation):

**Claude Code** ([docs](https://code.claude.com/docs/en/mcp))
```bash
claude mcp add --transport http <name> --scope user https://mcp.example.com/mcp     # remote
claude mcp add --scope user <name> -- npx -y package@1.2.3                         # local
```
Per project: `--scope project` writes `.mcp.json` at the root. `.mcp.json` supports `${VAR}` and `${VAR:-default}`
in `command`, `args`, `env`, `url` and `headers`, but **it only reads the environment Claude Code was started with**,
not `.env`. An entry with `url` must have `"type": "http"`.

**Codex** ([docs](https://developers.openai.com/codex/mcp))
```toml
# ~/.codex/config.toml  (or .codex/config.toml in a trusted project)
[mcp_servers.<name>]
command = "npx"
args = ["-y", "package@1.2.3"]
env_vars = ["MY_TOKEN"]          # forwards that variable from the environment

[mcp_servers.<remote>]
url = "https://mcp.example.com/mcp"
bearer_token_env_var = "MY_TOKEN"
```
Also: `codex mcp add <name> --env VAR=VALUE -- <command>` and `codex mcp login <name>` for OAuth.

**Gemini CLI** ([docs](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md))
```json
// ~/.gemini/settings.json  (or .gemini/settings.json in the project)
{
  "mcpServers": {
    "<name>": { "command": "npx", "args": ["-y", "package@1.2.3"], "env": { "MY_TOKEN": "$MY_TOKEN" } },
    "<remote>": { "httpUrl": "https://mcp.example.com/mcp", "headers": { "Authorization": "Bearer $MY_TOKEN" } }
  }
}
```
`url` is for SSE and `httpUrl` for streamable HTTP.

**OpenCode** ([V2 docs](https://opencode.ai/docs/mcp-servers) · [V1 docs](https://opencode.ai/v1/docs/mcp-servers))
```jsonc
// opencode.json in the project, or ~/.config/opencode/opencode.json(c)
{
  "mcp": {
    "<name>": { "type": "local", "command": ["npx", "-y", "package@1.2.3"],
                "environment": { "MY_TOKEN": "{env:MY_TOKEN}" }, "enabled": true },
    "<remote>": { "type": "remote", "url": "https://mcp.example.com/mcp",
                  "headers": { "Authorization": "Bearer {env:MY_TOKEN}" }, "enabled": true }
  }
}
```
In OpenCode V2, servers go under `mcp.servers` and use `disabled` instead of `enabled`. Also:
`opencode mcp add <name> --url <url>` (add `--global` for all projects).
