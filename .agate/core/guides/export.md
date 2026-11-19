# Artifacts: view, version, export

## Make one
- Path: `artifacts/YYYY-MM/YYYY-MM-DD-name.html`, or a folder with that name if it has several files.
- Self-contained HTML: styles and scripts inline; external libraries only from a CDN with a pinned version. It must
  read well on a phone.
- Add a line to `artifacts/INDEX.md` (date, title, what it is about), newest first.
- Don't overwrite one someone has seen: save the new version as `…-v2`.
- Boards with several screens: the `canvas` skill.
- Write it in the person's language (`agate.py start` prints it).

## Show it
`python3 -m http.server 8090` from the repo root (in the background) and share the link. On a remote machine, search
the library for a preview skill (`agate.py search preview`).
Publish to an external service only if `.agate/config.yml` sets `external_artifacts: true`.

## Export to PDF or PNG
```
python3 .agate/agate.py export pdf <file.html> [--paper A4|Letter] [--landscape]
python3 .agate/agate.py export png <file.html> [--full]
```
It uses headless Chrome/Chromium/Edge and keeps the design. To read, merge or fill existing PDFs, install the `pdf`
skill from the library.

## Print-ready HTML
- `@page { size: A4; margin: 16mm; }` (or Letter).
- `break-inside: avoid` on cards and tables; `break-before: page` for new sections.
- `print-color-adjust: exact` when background colors matter.
