# Secrets: API keys and tokens

The tool is `python3 .agate/agate.py env`. **Never open, print or quote `.env`.** Values never go through the chat.

## When something needs a key
1. Register it the moment it is needed (not before):
   `python3 .agate/agate.py env add NAME --where "where to get it" --for <what uses it>`
   It adds the name and the hint to `.env.example` (committed), an empty line to `.env` (not committed) and the owner to
   `.agate/env.json`. Connectors do this through `agate.py mcp add`.
2. Explain in plain words what the key is and where to get it.
3. The person sets the value, in this order of preference:
   - in a terminal: `python3 .agate/agate.py env set NAME` (hidden input; prints `saved: NAME (fp:xxxxxx)`);
   - or pasting it in `.env` with the editor;
   - or the `env-manager` app from the hub, if installed.
   If they paste a key in the chat anyway: **don't use it, don't save it, don't repeat it**. Tell them clearly (and
   firmly) that the key is now exposed (the chat history and the model provider have it), that they must **rotate it**
   at the provider, and offer the safe way for the new one (env-manager or the terminal). In Claude Code the
   `UserPromptSubmit` hook (`agate.py scan-prompt`) blocks such messages before they reach the model.

## Check without reading
`python3 .agate/agate.py env check [NAME…]` reports, without values: missing, empty, placeholder, quotes or spaces
around the value, duplicates, known formats (only the public prefix), lines that are not `NAME=value`, and severe
alerts if `.env` is tracked, in git history or not ignored.
- `--live`: asks each provider whether the key works (`ok` / `rejected (code)` / `network error` /
  `no live check`). It makes a network call: use it when a key seems wrong, not every time.
- `--fingerprint`: shows `fp:xxxxxx` (first 6 hex of SHA-256) to compare keys across machines without showing them.
- `--json` for scripts. Exit code 1 means there is something to fix.

## When it is no longer needed
`python3 .agate/agate.py env remove --for <package> [--yes] [--clear-local]` drops the variables only that package
used. Without `--yes` it only says what would change: confirm with the person first.

## Severe alerts
If `env check` says `.env` is tracked or in history: stop, tell the person, add `.env` to `.gitignore`, run
`git rm --cached .env`, and recommend rotating every key that was in it. Rewriting history is the person's call.
