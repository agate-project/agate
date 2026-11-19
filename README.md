<p align="center">
  <img src=".github/agate.svg" width="120" alt="Agate">
</p>

<h1 align="center">Agate</h1>

<p align="center">
  <b>Your AI projects, in git.</b> Like Claude Projects, but in a repo, with any model and any harness.<br>
  What gets discussed, decided and produced stays with the team.
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-0.4.5-2c5d88">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-a8492a">
  <img alt="template" src="https://img.shields.io/badge/GitHub-template-4c6680">
  <img alt="always-loaded context" src="https://img.shields.io/badge/always--loaded-%E2%89%881.35K%20tokens-2f6f4e">
</p>

---

## Why
- **Projects that remember, shared.** Memory, documents and artifacts live in the repo, not in someone's account.
- **Light by design.** About 1.35K tokens are loaded on every message; everything else is read only when needed.
- **Checks in code, not in prompts.** One command (`agate.py`) handles start-up, memory, keys, connectors and updates,
  and prints only what needs attention.
- **On demand.** Skills, extensions and apps come from the [Agate hub](https://github.com/agate-project/agate-hub)
  only when a project needs them.
- **Your language.** Instructions are in English for the model; it replies in each person's own language.

## Quick start

### Option A · Plain start (most projects)
```bash
gh repo create my-org/my-project --template agate-project/agate --private --clone
```
Or click **Use this template** above. Then open the folder in your harness (Orca, Claude Code…) and say hello:

> **You:** Hi, this project is to redesign the rewards module of our app. Two of us will work on it.
>
> **Agent:** Done: I noted what the project is about and who works on it. Where do you want to start, reviewing how
> the module works today or researching what other apps do with rewards?

No questionnaire: the first `start` sets the project up (folders, git hooks) and the agent fills in what the project
is about as you talk.

### Option B · Guided start with `quick-start`
For people who arrive with context to bring in: a Claude memory export, prompts, agents, skills, `CLAUDE.md` files or
documents from other projects.
```bash
gh repo create my-org/my-project --template agate-project/agate --private --clone \
  && cd my-project \
  && python3 .agate/agate.py add quick-start --yes
```
(`--yes` is your consent: the skill includes a script.) Open the folder and ask for the guided start:

> **You:** I want the guided start, and to bring what I use in Claude.
>
> **Agent:** Who else uses this project, and how do you like to work: should I ask before assuming, or assume and let
> you review at the end? *(at most 4 questions, only what it doesn't know yet)*
>
> **You:** One teammate. Ask me first. Here's a zip with my stuff.
>
> **Agent:** This is what I'd bring in: 23 memory notes, your discovery agent turned into a skill, a PDF skill that
> needs adapting (it uses claude.ai-only paths) and 2 documents. I skipped one file that looked like it had keys. You
> also use Google Sheets and Figma: want to connect them? Shall I apply the import?

Nothing is applied without your ok, and secrets are never copied. Without the terminal: create the project from the
template, open it and say "install quick-start"; the agent asks for the ok and does it.

## How it fits together
```mermaid
flowchart LR
  P["You"] -->|chat| A["Agent (any model)"]
  A -->|"at start"| S["agate.py start"]
  S --> M["memory/"]
  S --> K[".env status (never values)"]
  S --> U["updates (release tags)"]
  A -->|"when needed"| G[".agate/core/guides/"]
  A -->|produces| R["artifacts/ (local HTML, canvases)"]
  A -->|"on demand"| H["agate-hub: skills · extensions · apps"]
```

## What's inside
| Path | What it is |
|---|---|
| `AGENTS.md` | Short project instructions, read by any model (`CLAUDE.md` imports them). |
| `memory/` | What the agent keeps in mind. `shared/` is committed, `local/` stays on your machine. |
| `documents/` | Long material, read when needed. |
| `artifacts/` | What gets produced: local HTML pages and canvases, by month. Commentable and live with `agate.py serve`. |
| `archive/` | Archived items under their original path; only the index is committed. |
| `.agate/` | `agate.py` (the single command). `core/` is Agate itself (replaced by updates); the rest is this project's settings. |
| `.agents/skills/` | Skills: `canvas` and `web-research` ship with the base; the rest is installed on demand. |

## Everyday commands
The agent runs these for you; they're here so you know what exists.
```
python3 .agate/agate.py start              # start of a conversation (only prints what needs attention)
python3 .agate/agate.py memory add <name>  # save something worth remembering
python3 .agate/agate.py env set <NAME>     # set an API key (hidden input; never in the chat)
python3 .agate/agate.py serve              # view artifacts/canvases with live updates and comments
python3 .agate/agate.py tokens             # how much context the project takes
python3 .agate/agate.py check | update     # updates (only from release tags; scripts ask first)
python3 .agate/agate.py add <name>         # a skill, extension (product…) or app:<name> from the hub
```

## Security
- API keys are never printed or read by the agent; a hook blocks keys pasted in the chat before they reach the model.
- Packages come from release tags; anything with scripts asks first.
- Previews of local pages only through private channels (Orca's browser, a Tailscale link, SSH), never public tunnels.

## License
[Apache 2.0](LICENSE). See [`CHANGELOG.md`](CHANGELOG.md) for versions.
