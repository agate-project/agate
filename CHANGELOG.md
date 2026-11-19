# Changelog

## 0.4.4 · 2026-11-19
- Template slots in `AGENTS.md`: the base keeps its block as a template (`.agate/core/agents-block.md`); an extension
  gives only values (`"slots"` in its manifest) and `sync` rebuilds the same line, e.g. `When facts matter (e.g.
  market, users), check sources…`. Values from several extensions merge (deduplicated, max 8 per slot). Without
  extensions that fill a slot, nothing changes. The agent only sees the final line.
- `build.py` fails if the template and the shipped block diverge.
- No migration needed.

## 0.4.3 · 2026-11-19
- Apache 2.0 license (`LICENSE`).
- README with the Agate icon (`.github/agate.svg`), badges, quick start and how the pieces fit.
- No behavior changes: nothing to migrate.

## 0.4.2 · 2026-11-19
- Memory as commands: `agate.py memory add|update|remove|list|check` writes each entry with its frontmatter and keeps
  its line in `memory/INDEX.md` in sync; `check --fix` adds missing index lines and drops broken ones.
- `agate.py start` prints the memory index itself while it is short (`memory_index_inline_lines`, default 40), so
  reading the index and running start is one step; it also warns about memory problems and suggests saving decisions
  after several work commits without memory changes (`memory_nudge_commits`).
- New `config.yml` keys: `memory_index_lines`, `memory_index_inline_lines`, `memory_stale_days`,
  `memory_nudge_commits`.

- `agate.py tokens --real`: what really entered the first turn of the last Claude Code sessions (usage only, no
  conversation text), split into Agate's always-loaded part and the rest (harness prompt, tools). `--mcp`: weight of
  each local connector's tool definitions. `memory/INDEX.md` has its own row; `start` warns above
  `tokens_first_turn_warn` / `tokens_mcp_tools_warn` (cached, refreshed at most weekly).
- `.ignore` / `.rgignore`: Agate's own files (.agate/, skill references, caches) stay out of ripgrep-based searches;
  reading by path still works.
- Supply chain: the base and the hub install and update only from their latest release tag (vX.Y.Z), never from the
  branch tip; the lock records tag + commit. Pinned sources (Anthropic) move only with `update <name> --ref <commit>`.
  Packages with scripts ask first even from trusted sources (`--yes`); `update` lists `scripts changed:`.
- Fresh projects set themselves up: the first `start` creates the folders and turns on the git hooks, and tells the
  agent once to fill the project description as the person talks — no questionnaire. Hub skill `quick-start`
  (on demand, text-only) for a short guided start.
- Keys pasted in the chat: `agate.py scan-prompt` (Claude Code `UserPromptSubmit` hook) blocks a message with a known
  key format before it reaches the model and asks to rotate it; the guide says never use, store or repeat it.
- Session-start hook: `agate.py start --hook` loads start automatically in Claude Code; a later manual `start` in
  the same harness answers in one line instead of repeating it.
- Live view: `agate.py serve` streams changes (Server-Sent Events) — canvases reload only the board that changed,
  re-layout on `canvas.json` and refresh comments; plain artifacts reload keeping the scroll; shows who else is
  viewing. AI cursor at no token cost: `agate.py serve notify --from-hook` (Claude Code `PostToolUse`) marks the
  edited board; "Follow the AI" (key F).
- Fix: the conversational style's frontmatter is valid YAML; a test checks every shipped frontmatter.

### Migrating from 0.4.1
- `agate.py update` adds `"releases": "tags"` to the `agate` source and a `base` entry to `.agate/library.json` if
  missing. Publishing a version requires pushing a `vX.Y.Z` tag to agate and agate-hub.

## 0.4.1 · 2026-11-19
- **`start` says more, only when there is something to say:** `Reply in`, then (if known) `Person` (name · working
  style · link to longer notes), `Last session` (latest noted chat or daily log, last 14 days), a line when this
  harness has no native web search, a short skills list only in harnesses that don't load Agent Skills, and an
  `Attention` list ordered by severity where each item carries its action and guide. At most 10 lines.
- **Preferences in YAML:** `memory/local/preferences.yml` (or `memory/local/people/<name>.yml`) and
  `memory/shared/project.yml`. Long notes stay in a `.md` referenced by `notes:`.
- **Update checks with backoff:** first conversation of the day, then 1h → 2h → 1d (`update_check_schedule`), with
  `git ls-remote` only; a pending update is mentioned at most once a day (`update_notice_hours`) and can be
  snoozed (`agate.py update --snooze 7d`). Never applied without the person's ok.
- **Skill descriptions are measured:** `agate.py tokens` shows their subtotal; `start` warns when they pass
  `tokens_skill_descriptions_warn`. When every provider is the same uncalibrated estimate, `tokens` prints one row.
- **Hub apps on demand:** `agate.py add app:<name>` / `remove app:<name>` (into `.agate/apps/`); they add no
  always-loaded context, and `start` points to an installed app only when relevant (e.g. the key manager).
- `agate.py env set NAME --stdin` reads the value from stdin (for apps); it is never echoed.
- **Comments on canvases and artifacts:** `agate.py serve` (127.0.0.1 only, serves `artifacts/`, `documents/` and the
  canvas engine, nothing else) adds a comments API. Canvases get a «Comment» button (key `C`): pins, threads,
  replies, resolve, `#comment-<id>` links; any HTML artifact can include `.agate/core/canvas/comments.js`. Stored
  next to the artifact (`comments.json` / `x.comments.json`, committed). `start` mentions new comments in one line;
  `agate.py comments list --new | reply | resolve | seen`. Guide: `.agate/core/guides/comments.md`.

### Migrating from 0.4.0
- Nothing to do by hand: the first `agate.py start` (or `lang`) converts `memory/local/preferences.md`,
  `memory/local/people/*.md` and `memory/shared/project.md` with frontmatter into `.yml`; any text below the
  frontmatter stays in the `.md` and is referenced with `notes:`.

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
