# Skills and the library

Skills live in `.agents/skills/<name>/SKILL.md` (open Agent Skills standard; `.claude/skills` points there). The base
ships `canvas` and `web-research`; everything else comes from the library (sources in `.agate/library.json`,
starting with Anthropic's skills and the Agate hub).

## Search before improvising
If asked for something with a well-known format or technique (PDF, Word, PowerPoint, Excel, diagrams, testing a web
page, previewing a page from a remote machine…), search first:
```
python3 .agate/agate.py search <topic>
```

## Install
```
python3 .agate/agate.py add <source>/<skill>      # e.g. anthropic/pdf
python3 .agate/agate.py add pack:<name>           # documents, design, writing, build
```
- Trusted sources (Agate hub, Anthropic): install on your own and say so in one line
  ("Installed `pdf` from Anthropic, Apache 2.0").
- Any other source: show what the skill contains (instructions and scripts) and ask before using `--yes`.
- Use it in the same chat: read the new `SKILL.md` and follow it (some harnesses only list it from the next chat).
- Dependencies: `python3 .agate/agate.py doctor <skill>`. Install light ones (Python/npm packages); ask before heavy
  ones (LibreOffice).
- Commit it separately: `skills: add <name> (<source>@<ref>)`.

## Keep them current
- `python3 .agate/agate.py check` lists updates for every package; `update [name] --yes` applies them.
- Don't hand-edit library skills (`verify` detects it and `update` would overwrite it). To adapt one, create your own
  skill with another name.
