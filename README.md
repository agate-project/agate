# Agate

A base for working projects with AI agents, with any model (Claude, Codex, Gemini…) and any harness (Orca, Claude
Code, OpenCode…). It is for the same things people use Claude web or desktop for (conversing, writing, analyzing,
researching, planning, preparing documents), but **in a repo**: what gets discussed, decided and produced lives in
git, shared with the team and with any model.

Everything here is in English because the agent reads it. The agent replies, and writes artifacts and documents, in
each person's own language.

## What it includes
| Path | Purpose |
|---|---|
| `AGENTS.md` | Project instructions, read by any model (`CLAUDE.md` imports them). Kept short on purpose. |
| `memory/` | What the agent keeps in mind. Index in `memory/INDEX.md`; `shared/` is committed, `local/` is not. |
| `documents/` | Long material consulted when needed. |
| `artifacts/` | What gets produced to view or use, as local HTML, by month. |
| `archive/` | Archived items under their original path; only `archive/INDEX.md` is committed. |
| `.agate/` | `agate.py`, the single command. `core/` is Agate itself (replaced by updates; don't edit). `config.yml`, `mcp/`, `project/` and `library.json` belong to the project. |
| `.agents/skills/` | Skills. The base ships `canvas` and `web-research`; the rest is installed on demand. |

Procedures (memory format, archiving, past chats, skills, connectors, secrets, export, extensions, context budget)
live in `.agate/core/guides/`; the agent reads each one only when it needs it.

## Start a new project
1. On GitHub, **Use this template** to create the project repo (private).
2. Clone it with a partial clone, so archived content isn't downloaded:
   ```
   git clone --filter=blob:none <project-url>
   ```
3. Edit the top of `AGENTS.md` (what the project is) and its "This project" section.
4. Open it in your harness (Orca, Claude Code, Codex…) and start talking. API keys are added only when something
   needs them.

## Common commands
```
python3 .agate/agate.py start            # what the agent runs at the start of a conversation
python3 .agate/agate.py check            # available updates: base, extensions, skills
python3 .agate/agate.py update --yes     # apply them
python3 .agate/agate.py add ext:<name>   # install an extension from the hub (skills: add <source>/<skill>)
python3 -m http.server 8090              # view artifacts and canvases at http://localhost:8090/artifacts/
```

## Version
See [`CHANGELOG.md`](CHANGELOG.md).
