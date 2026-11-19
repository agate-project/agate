# Memory entries

## Where
- `memory/shared/`: the project's memory for the whole team (committed). A profile of someone using the project goes
  here only if really needed (role, how they like to receive information), with nothing sensitive.
- `memory/local/`: this machine only, not committed (language preference, tested capabilities, private notes).
- Shared checkout used by several people: keep each person's preferences in `memory/local/people/<name>.md`.
- Optional daily log: `memory/shared/log/YYYY-MM-DD.md` (what was worked on and decided); move the important parts
  to the index later.

## Format
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
