# Add a connector (MCP)

The tool is `python3 .agate/agate.py mcp`; the project's list is `.agate/mcp/servers.json`. Explain things to the person in their language and in plain words.

## What an MCP is

An **MCP** (Model Context Protocol) server is a **connector**: it gives the agent tools to use a service, such as
reading a Figma board, creating a ClickUp task or querying a database. There are two kinds:

- **Local:** a program that runs on the person's machine (for example, a read-only one for a database). It almost
  always needs a token or a password.
- **Remote:** hosted by the provider and used through a URL (Figma, Linear, Notion…). Many are authorized by
  **signing in through the browser**, with no token; others ask for a key.

An MCP server is code that runs with **the person's** permissions and reads whatever it is asked to. Install with care.

## Project or system level?

| Level | When | Where it lives |
|---|---|---|
| **Project** (the usual) | Connectors the project needs and the team shares | `.agate/mcp/servers.json` (committed) + each person's tokens in `.env` |
| **System / harness** | Personal connectors used in **all** of someone's projects (their Notion, their email) | Each harness's global configuration + tokens in `~/.config/agate/.env` |

## Shortcut for Claude in Orca

With Claude, many connectors **already come from the claude.ai account** (Figma, ClickUp, Google Drive, Docs,
Sheets, Slides, Notion, Linear, Slack, Atlassian, Intercom, monday…). Nothing to configure: they only need to be
**authorized** once (claude.ai → Settings → Connectors, or `/mcp` in Claude Code). `.agate/mcp/servers.json` is for what's
missing, and so other models (Codex, Gemini, OpenCode…) get the same.

## How the agent adds a connector

When someone asks "connect to X":

1. **Check whether it already exists.** Does it come from the claude.ai account? Is it in `.agate/mcp/servers.json`
   (`agate.py mcp list`)? If so, it only needs authorizing or a token: say so and stop.
2. **Otherwise, offer two paths:** "Do you have the documentation for X's MCP? Send me the link or paste it here" or
   "I'll look it up".
3. **If they say "look it up"**, research with the `web-research` skill:
   - Is there an **official MCP** (from the provider itself) or only community ones?
   - Local or remote? How is it authorized (sign-in, token, none)?
   - Is it maintained (latest version, documentation, who publishes it)?
4. **Show what you found, recommend, and wait for the ok.** Rules:
   - **Official first.**
   - Community ones **only with explicit confirmation**, explaining the risk.
   - **Never** an unknown or undocumented package, even if they're in a hurry.
   - Pin the package version (`package@1.2.3`), not "latest".
5. **With the ok, set everything up:**
   ```
   python3 .agate/agate.py mcp add <name> --type local --command npx --env VAR \
       --where "where to get the token" --docs <url> --by <who> --args -y package@1.2.3
   python3 .agate/agate.py mcp add <name> --type remote --url <url> --auth oauth|token|none [--env VAR]
   ```
   This records the connector in `servers.json`, adds the variable to `.env.example` (with where to get it) and
   leaves an **empty** line in that person's `.env`. Then:
   ```
   python3 .agate/agate.py mcp sync     # generates each harness's config
   python3 .agate/agate.py mcp check    # checks for missing variables (without showing values)
   ```
   Note the connector in `.agate/mcp/README.md` (what we use it for and how it's authorized).
6. **Ask for the token and test the connection.** "Paste your token into `.env`, line N. You get it at …". Then
   restart or reload the harness and try a simple tool from the connector. If it fails, say so with the error;
   don't make anything up.
7. **If no MCP exists**, offer alternatives:
   - use the service's **API** with a project script;
   - **export** the data to CSV and put it in `documents/`;
   - **build** an MCP server with Anthropic's `mcp-builder` skill. That's a project in itself: **propose** it, don't
     do it on your own.

## Tokens: where they go and where they don't

- **They go in `.env`** (not committed). **Each person has their own `.env`**: everyone uses their own token, with
  their own permissions.
- **`.env.example` is committed**: only empty names and where to get each one. When someone opens the project, the
  agent compares (`agate.py env check`) and asks for what's missing.
- **Ask people to paste tokens into `.env` with Orca's editor, not into the chat.** What's written in the chat stays
  in the history and reaches the model provider. If someone pastes a token in the chat anyway: save it to `.env`,
  warn about the risk and suggest rotating it when they can.
- No generated file (`.mcp.json`, `.gemini/settings.json`, `opencode.json`, `.codex/config.toml`) contains secrets:
  local connectors start with `python3 .agate/agate.py mcp run <name>`, which reads `.env` and passes the server
  **only** the variables it declares.

For tokens and `.env` in general see `secrets.md`. If it fails see `mcp-troubleshoot.md`.
