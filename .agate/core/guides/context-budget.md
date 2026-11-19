# Context budget: how big is this project for the model

The tool is `python3 .agate/agate.py tokens`. `agate.py start` already runs a quick offline check once a week and
prints one line only when a threshold is crossed (installed skill descriptions included).

## Read the numbers
`python3 .agate/agate.py tokens [paths…] [--provider claude|gemini|openai|all] [--exact] [--json]`
- Groups: **always loaded** (AGENTS.md, CLAUDE.md, output style, skill descriptions, memory index — paid in every
  message), **shared memory**, **corpus** (documents/ + artifacts/) and the heaviest files.
- One number per provider, each with its source: `exact` (official counter), `calibrated` (estimate corrected by a
  past exact count, ±5 %) or `estimate` (characters / 3.5, ±15 %). Tokenizers differ: never average providers.
  Warn with the highest number among the models the team uses.
- `--exact` needs credentials: Claude via `ANTHROPIC_API_KEY` or an `ant` login; Gemini via `GEMINI_API_KEY`;
  OpenAI only if `tiktoken` is installed. If missing or offline it falls back to the estimate. Each exact run updates
  that provider's calibration in `memory/local/token-calibration.json`. Register keys with `env add` (see secrets.md).
- PDFs count their extracted text (needs `pdftotext`); otherwise they are skipped with a note.

## What really enters the first turn
The groups above are Agate's part. The harness adds its own system prompt and every connector's tool definitions.
- `agate.py tokens --real [--sessions N]`: reads the `usage` of the first turn of this repo's last N Claude Code
  sessions (Orca's Claude sessions are the same transcripts) and splits it: Agate always-loaded vs the rest. Only
  numbers are read; no conversation text. Cached in `memory/local/token-real.json`.
- `agate.py tokens --mcp`: starts each local connector, asks `tools/list` and estimates its tool definitions
  (remote connectors are skipped: the harness holds their authorization). Cached in `memory/local/mcp-tools.json`.
- `start` refreshes the `--real` cache at most weekly and warns in one line above `tokens_first_turn_warn` or
  `tokens_mcp_tools_warn`, naming the biggest part and the action.

## Agate stays out of searches
`.ignore` and `.rgignore` at the project root hide `.agate/`, skill `references/` and caches from ripgrep-based
searches (Claude Code's Grep uses ripgrep), so searching the project returns the project, not Agate's code.
Reading a file by its path still works (AGENTS.md points to guides by path). To search them anyway:
`rg --no-ignore-dot <pattern>`, or remove the line from `.ignore`/`.rgignore`.

## What to do when a threshold is crossed
Thresholds live in `.agate/config.yml` (`tokens_*`); the project may change them.
| Signal | Action (propose it to the person first) |
|---|---|
| Always loaded > `tokens_always_loaded_warn` | Trim `AGENTS.md` "This project" section; move procedures to guides or skills |
| Memory index > `tokens_memory_index_lines` lines | Group or condense index lines |
| Shared memory > `tokens_shared_memory_warn` | Condense entries; archive old ones (archive.md) |
| Corpus > `tokens_corpus_index` | Add a search index over documents/ (a skill from the library) |
| Corpus > `tokens_corpus_rag` | RAG / semantic search; keep only summaries in reach |
| A file > `tokens_file_large` | Summarize it into a shorter document, or split it by topic |
| First turn > `tokens_first_turn_warn` | See `--real`/`--mcp`: disable unused connectors, condense the memory index |
| MCP tools > `tokens_mcp_tools_warn` | Disable connectors nobody uses in `.agate/mcp/servers.json` (`mcp sync` after) |
| Skill descriptions > `tokens_skill_descriptions_warn` | Remove skills nobody uses (`agate.py remove <name>`); every installed skill's description is loaded in every message |

The `context-meter` app from the hub shows the same numbers visually and over time, if the person wants it.
