# Extensions and base updates

Extensions add skills, tools and an instructions block for a specific use (e.g. product). They come from the Agate
hub and are installed on demand, like skills and hub apps.

## Install
```
python3 .agate/agate.py add ext:<name>           # e.g. ext:product; downloads only that folder of the hub
```
It adds its files and its own `<!-- agate-<name>:begin/end -->` block to `AGENTS.md`.

## Update the base and every package
```
python3 .agate/agate.py check                    # base, extensions and skills in one table
python3 .agate/agate.py update                   # shows what would change, applies nothing
python3 .agate/agate.py update --yes             # apply (only with the person's ok)
python3 .agate/agate.py update --snooze 7d       # the person said "later": silence the notice for a while
```
`agate.py start` checks for updates by itself (first conversation of the day, then 1h → 2h → 1d; `git ls-remote`
only) and mentions a pending one at most once a day. Offer it; never apply without the person's ok.
Updates replace `.agate/core/`, the base skills and the `agate:begin/end` blocks of `AGENTS.md`, `CLAUDE.md` and
`.env.example`. They never touch memory, documents, artifacts, the archive, `.agate/config.yml`, `.agate/mcp/`,
`.agate/project/` or the project's own skills.

## Apps (on demand only)
Hub apps (e.g. `env-manager`, `context-meter`) are never installed by default and add nothing to the always-loaded
context; `start` points to an installed app only when it is relevant.
```
python3 .agate/agate.py add app:<name>           # into .agate/apps/<name>/ (project layer), recorded in lock.json
python3 .agate/agate.py remove app:<name>
```

## Rules
- Project-specific instructions go outside the blocks (the "This project" section) or in new files.
- After an update, read the `CHANGELOG.md` entry and tell the person in one or two lines what changed.
- The base, extensions and apps are installed and updated from release tags (`vX.Y.Z`); `check` shows tag → tag and
  never offers the branch tip. A package with scripts (every app, extensions with code) needs `--yes` after the
  person's ok; `update` lists `scripts changed:` first.
