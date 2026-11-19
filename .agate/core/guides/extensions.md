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
```
Updates replace `.agate/core/`, the base skills and the `agate:begin/end` blocks of `AGENTS.md`, `CLAUDE.md` and
`.env.example`. They never touch memory, documents, artifacts, the archive, `.agate/config.yml`, `.agate/mcp/`,
`.agate/project/` or the project's own skills.

## Rules
- Project-specific instructions go outside the blocks (the "This project" section) or in new files.
- After an update, read the `CHANGELOG.md` entry and tell the person in one or two lines what changed.
