# This project's connectors (MCP)

The connectors **this project** uses are recorded here. It starts empty: each connector is added when someone asks
for it, following [`.agate/core/guides/mcp-add.md`](../core/guides/mcp-add.md).

| File | What it is | In git? |
|---|---|---|
| `servers.json` | The project's connector list (no secrets, only variable names) | Yes |
| `<name>.md` | Usage notes for a connector, if needed (what it's for here, limits, permissions) | Yes |
| `../.env.example` | Names of the variables needed and where to get each one | Yes |
| `../.env` | **Each person's** tokens | **No** |

Each harness's configuration (`.mcp.json`, `.gemini/settings.json`, `opencode.json`, `.codex/config.toml`) is
generated with `python3 .agate/agate.py mcp sync` from `servers.json`. Don't edit them by hand: regenerate them.
Git hooks (`.agate/core/hooks/`) regenerate them after pulls and before commits that change `servers.json`; a harness
Agate doesn't know can be added in `.agate/project/mcp.py` (see the guide).

## Connectors in this project

None yet. When one is added, note it here: `- **<name>** — what we use it for · how it's authorized`.

## `servers.json` format

```json
{
  "servers": {
    "<name>": {
      "type": "local",
      "command": "npx",
      "args": ["-y", "server-package@1.2.3"],
      "auth": "token",
      "env": ["CLICKUP_API_TOKEN"],
      "docs": "https://…",
      "official": true,
      "added": "YYYY-MM-DD",
      "by": "Name of who added it"
    },
    "<other>": {
      "type": "remote",
      "url": "https://mcp.example.com/mcp",
      "auth": "oauth",
      "env": [],
      "docs": "https://…",
      "official": true,
      "added": "YYYY-MM-DD",
      "by": "Name of who added it"
    }
  }
}
```

| Field | Meaning |
|---|---|
| `type` | `local` (a program running on the machine) or `remote` (hosted by the provider, by URL) |
| `command`, `args` | `local` only: how it starts. Pin the package version (`@1.2.3`). `args` may use `${VAR}` from the declared variables |
| `url` | `remote` only: the server address |
| `auth` | `oauth` (sign in through the browser, no token), `token` (key in `.env`) or `none` |
| `env` | **Names** of the variables it needs. Their values go in `.env`, never here |
| `token_env` | `remote` with `auth: token` only: which of the `env` variables is the token (default: the first) |
| `header`, `token_prefix` | `remote` with token only: header and prefix (default `Authorization` and `Bearer `) |
| `docs` | Link to the connector's documentation |
| `official` | `true` if the provider itself publishes it; `false` if it's a community one (installed with confirmation) |
| `added`, `by` | When it was added and who asked for it |
