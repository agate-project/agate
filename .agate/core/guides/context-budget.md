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
| Skill descriptions > `tokens_skill_descriptions_warn` | Remove skills nobody uses (`agate.py remove <name>`); every installed skill's description is loaded in every message |

The `context-meter` app from the hub shows the same numbers visually and over time, if the person wants it.
