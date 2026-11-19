# Changelog

## 0.4.0 · 2026-11-19
- **One command:** `python3 .agate/agate.py <command>` replaces the separate tools. `start`, `check`, `update`,
  `add`, `remove`, `search`, `list`, `verify`, `doctor`, `sources`, `lang`, `mcp …`, `chats …`, `export …`.
- **Everything is a package:** the base, extensions and skills are recorded in one lock, `.agate/lock.json`.
  `check` lists available updates for all of them in one table; `update` shows the changes and applies them with
  `--yes`.
- **Implementation hidden in `.agate/`:** the project root shows only `AGENTS.md`, `CLAUDE.md`, `README.md`,
  `memory/`, `documents/`, `artifacts/` and `archive/`. Inside `.agate/`, `core/` is the base (replaced wholesale by
  updates: don't edit it) and the rest is the project layer: `config.yml`, `mcp/`, `project/`, `library.json`.
- **`agate.py start`** prints only what needs attention: normally one line, `Reply in: <language>`. MCP, memory index
  and package-update notices appear only when something is wrong (updates are checked at most once a week).
  `agate.py lang set <code>` saves the reply language (per person on a shared checkout with `--person`).
- **`.agate/config.yml`** (project settings): `external_artifacts: false` by default.
- **`.env` on demand:** `.env.example` starts empty; variables are added the moment something needs them with
  `agate.py env add NAME --where "…" --for <package>` (connectors do it through `mcp add`; web-research when the
  person opts into Exa/Tavily). Owners are recorded in `.agate/env.json`, so `env remove --for <package>` drops what
  nobody uses and `start` only reports missing variables of things in use.
- **`agate.py env set NAME`** asks for the value with hidden input and writes `.env` atomically (`saved: NAME (fp:…)`).
  **`agate.py env check`** validates `.env` without showing values: missing, empty, placeholders, quotes/whitespace,
  duplicates, known formats (public prefix only), broken pastes, and severe alerts if `.env` is tracked or in git
  history. `--live` asks each provider whether the key works; skills can ship `env_validators.py`.
- **`agate.py tokens`:** context the project takes (always loaded, shared memory, corpus, heaviest files), one number
  per provider (Claude, Gemini, OpenAI) with its source: exact (official counters, `--exact`), calibrated or
  estimated. Never averaged across providers. Thresholds in `.agate/config.yml` (`tokens_*`) turn into
  recommendations; `start` checks once a week and prints one line only when a threshold is crossed.
- Base updates create project-layer files that are missing (`seed`) and only merge new default sources into
  `.agate/library.json`; they never overwrite the project's edits.

### Migrating from 0.3.0
- Moves: `tools/agate/*.py` → `.agate/core/lib/` (`skills-sync.py` → `skills_sync.py`), `tools/canvas/` →
  `.agate/core/canvas/`, `guides/` → `.agate/core/guides/`, `.agate/hooks/` → `.agate/core/hooks/`, `mcp/` →
  `.agate/mcp/`, `tools/project/` → `.agate/project/`. Then delete the empty `tools/`.
- Canvases: replace `../../../tools/canvas/` with `../../../.agate/core/canvas/` in each `artifacts/**/*.canvas/index.html`.
- Git hooks: run `python3 .agate/agate.py mcp hooks install` (sets `core.hooksPath` to `.agate/core/hooks`), then
  `python3 .agate/agate.py mcp sync` so MCP configs call `.agate/agate.py mcp run|headers`.
- Lock: the first `agate.py` run imports `.agate/skills.lock.json` and the `source` recorded in manifests into
  `.agate/lock.json`, then removes the old skills lock.
- `.env.example` is no longer a base block: delete the `# agate:begin` / `# agate:end` lines (keep the variables you
  use). For each variable something uses, run `agate.py env add NAME --where "…" --for <package>` once so it gets an
  owner in `.agate/env.json`; connectors already registered can be re-added with `agate.py mcp add … --force`.
- Copy the `tokens_*` thresholds from the new `.agate/config.yml` template if you want to override them.
- Commands: `sync.py --from X` → `agate.py update --from X --yes`; `sync.py add X` → `agate.py add X`;
  `sync.py check` → `agate.py check`; `skills-sync.py <cmd>` → `agate.py <cmd>`; `mcp.py`, `chats.py`, `export.py`
  → `agate.py mcp|chats|export`.

## 0.3.0 · 2026-11-19
- Everything in the base (instructions, skills, guides, tools) is now in English, since the agent is the one reading
  it. New **language rule**: the agent saves each person's language the first time they write
  (`memory/local/preferences.md`, plus the project default in `memory/shared/project.md`) and replies, and writes
  artifacts and documents, in that language.
- Skills library: `tools/agate/skills-sync.py` (`sources`, `search`, `add`, `remove`, `update`, `list`, `verify`,
  `doctor`), `.agate/library.json` with Anthropic's skills and packs (`documents`, `design`, `writing`, `build`), and
  `.agate/skills.lock.json` for what is installed. The agent searches for and installs the skill it is missing.
- Connectors (MCP): `mcp/` (empty), `guides/how-to-use-mcp.md` and `tools/agate/mcp.py` (`list`, `check`, `add`,
  `sync`, `run`, `headers`, `install`). Generates the configuration for Claude Code, Codex, Gemini CLI and OpenCode
  without secrets.
- Past chats: `tools/agate/chats.py` keeps in `memory/local/chats.json` where each chat of the repo lives in each
  harness (Orca, Claude Code, OpenCode, Codex, Gemini), so they can be searched, read and resumed.
- Export artifacts to PDF or PNG with `tools/agate/export.py`, keeping the design.
- New canvas engine: sections with automatic layout, sizes (`preset`), pending boards, arrows, colored notes,
  minimap, keyboard shortcuts, per-board links (`#id`), no text selection while dragging, and a localized interface
  (`"lang"` in `canvas.json`).

- MCP configs stay up to date: `mcp.py sync` stores a fingerprint of `mcp/servers.json`; `check` reports "out of
  date" and `sync --if-stale` regenerates only when needed.
- Git hooks in `.agate/hooks/` (enable once with `mcp.py hooks install`): regenerate after pull/checkout/rebase and add
  generated files on commits that change `servers.json`.
- `mcp.py doctor <name>` diagnoses a registered connector that does not answer (config, token, MCP handshake via
  `run <name> --test`, chat-start reminders, unknown harness).
- Project extensions: `tools/project/mcp.py` can add harnesses and hooks; it only runs once approved on each machine
  (own changes auto-approved, others' need `mcp.py extension review|approve`). `tools/project/` is never touched by
  `sync.py`.
- Agate hub: extra skills and extensions live in `agate-project/agate-hub` and are downloaded on demand.
  `sync.py add <extension>` installs one (only that folder is downloaded); `sync.py check` lists available updates
  for the base and each installed extension. The library source `agate` now points to the hub.

### Migrating from 0.2.0
- `.env.example` now has a base block: wrap the Exa and Tavily lines with `# agate:begin` and `# agate:end` before
  syncing. Project variables go outside the block.
- Create `mcp/servers.json` with `{"servers": {}}` if it doesn't exist.
- Library packs were renamed to English: `documentos` → `documents`, `diseno` → `design`, `escritura` → `writing`,
  `construir` → `build`.

## 0.2.0 · 2026-11-19
- Agnostic base: works for any use (conversing, writing, analyzing, researching, planning), not tied to one area.
- `conversational` style rewritten to converse like Claude web/desktop.
- Memory: `memory/shared/` (committed) and `memory/local/` (not committed) replace `team/`, `people/` and
  `personal/`. Tested capabilities from `web-research` move to `memory/local/capabilities.json`.
- Generic archive: `archive/` keeps the original path (artifacts, documents or memory) and its index
  `archive/INDEX.md` is committed. `artifacts/ARCHIVED.md` is removed.
- Expansions: `sync.py` installs and updates expansions (`.agate/expansions/<name>.json`, an
  `agate-<name>:begin/end` block in `AGENTS.md`).

### Migrating from 0.1.0
- Move `memory/team/*` and `memory/people/*` to `memory/shared/`, and `memory/personal/*` to `memory/local/`.
- Move archived items to `archive/<original path>` and move the rows of `artifacts/ARCHIVED.md` to `archive/INDEX.md`.
- Update `.gitignore`: `memory/local/`, `archive/*` and `!archive/INDEX.md`.

## 0.1.0 · 2026-11-19
- First version of the base.
- Structure: `memory/`, `documents/`, `artifacts/` by month and a local `archive/`.
- Instructions for any model in `AGENTS.md`; `CLAUDE.md` imports them.
- `conversational` output style for Claude Code.
- Skills: `web-research` and `canvas`.
- Canvas engine in `tools/canvas/` and base sync in `tools/agate/sync.py`.
