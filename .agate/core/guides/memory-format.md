# Memory entries

## Commands (use these; they keep the file and the index in sync)
```
python3 .agate/agate.py memory add NAME --description "one line" [--type decision] [--scope shared|local] [--body - ]
python3 .agate/agate.py memory update NAME [--description "…"] [--body - | --append "…"]
python3 .agate/agate.py memory remove NAME --yes
python3 .agate/agate.py memory list [--scope shared] [--stale 120]
python3 .agate/agate.py memory check [--fix]
```
- `add` writes `memory/<scope>/<name>.md` with its frontmatter and the index line; it refuses if the entry exists
  (then `update`). `--body -` reads the text from stdin.
- `check --fix` adds missing index lines and drops broken ones; it never deletes entries. `agate.py start` tells you
  when something needs it, and prints the index itself while it is short.

## Where
- `memory/shared/`: the project's memory for the whole team (committed). A profile of someone using the project goes
  here only if really needed (role, how they like to receive information), with nothing sensitive.
- `memory/local/`: this machine only, not committed (preferences, tested capabilities, private notes).
- Shared checkout used by several people: each person's preferences in `memory/local/people/<name>.yml`.
- Optional daily log: `memory/shared/log/YYYY-MM-DD.md` (what was worked on and decided); move the important parts
  to the index later.

## Preferences (short and structured → YAML)
Flat `key: value` YAML, written with `agate.py lang set` or by you:
- `memory/local/preferences.yml` (or `memory/local/people/<name>.yml`): `name`, `language`, `style` (one line, e.g.
  `prefers being asked before assumptions`), `notes` (path to a longer .md, read only when needed),
  `preview_identity`, `consent_<thing>: YYYY-MM-DD`.
- `memory/shared/project.yml`: `default_language` and other short project defaults.
- Long text goes in a .md referenced by `notes:`. JSON is only for tool state (`state.json`, `chats.json`…).

## Format (what `memory add` writes)
One file per entry:
```
---
name: short-name
description: one line; it decides whether anyone opens it
updated: YYYY-MM-DD
type: optional and free (decision, finding, person, data…)
---
Body. Lead with the fact or decision, then why.
```
An entry can point to data (`.json`, `.csv`) or to a document instead of copying it.

## Index
- `memory/INDEX.md`: one line per entry, `- [Title](path) — what it is about`.
- It is read at the start of every conversation: keep it under ~150 lines; group or summarize when it grows
  (`agate.py start` warns when it passes the limit).
- `documents/INDEX.md` works the same way for documents: one line per document or folder.

## Keeping it true
- Before creating an entry, search for an existing one and update it (and its `updated` date).
- If something turns out false or stale, fix it or delete it, and update the index.
- Write team memory in the project's language (see `agate.py start`); file names and keys stay in English.
