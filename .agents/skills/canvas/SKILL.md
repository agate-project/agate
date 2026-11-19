---
name: canvas
description: Create or update a canvas, a pan-and-zoom board that shows several screens, documents or artboards side by side, grouped in sections (flows, comparisons, multi-screen prototypes, high-res UI mockups, opportunity maps). Use it when several pieces need to be seen together, options compared, or a journey explained visually.
---

# Canvas

A canvas is just another artifact: it lives in `artifacts/` and is committed. It is viewed in the browser with the
engine in `.agate/core/canvas/`: drag to pan, wheel or pinch to zoom, double-click a board to frame it and interact with it.

## When to use it
- There are several screens, options or pieces worth seeing **together**: a flow, variants of an idea, a before and
  after, app mockups, an opportunity map.
- For a single page (a report, a table), a standalone HTML file in `artifacts/` is better.

## Format
```
artifacts/YYYY-MM/YYYY-MM-DD-name.canvas/
  index.html       ← loads the engine; rarely changes
  canvas.json      ← title, language, sections, boards, notes and arrows
  boards/<id>.html ← one board = one self-contained HTML file
```

`index.html` (the engine path assumes the depth `artifacts/YYYY-MM/<canvas>/`; set `lang` to the person's language):
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Canvas title</title>
  <link rel="stylesheet" href="../../../.agate/core/canvas/canvas.css">
</head>
<body>
  <script src="../../../.agate/core/canvas/canvas.js"></script>
</body>
</html>
```

`canvas.json` (only `title` and `boards` are required):
```json
{
  "title": "Onboarding: 3 options",
  "description": "What we tried and what we recommend",
  "lang": "en",
  "created": "2026-11-19",
  "entry": "option-a",
  "links": [{ "label": "← Earlier research", "href": "../2026-11-12-onboarding.canvas/" }],
  "sections": [
    { "id": "options", "title": "Options", "subtitle": "Three ways to sign up" },
    { "id": "decision", "title": "Decision" }
  ],
  "boards": [
    { "id": "option-a", "title": "A · Short sign-up", "src": "boards/option-a.html",
      "section": "options", "preset": "mobile", "note": "The simplest one" },
    { "id": "option-b", "title": "B · With tutorial", "src": "boards/option-b.html",
      "section": "options", "preset": "mobile" },
    { "id": "option-c", "title": "C · With invitation", "section": "options", "preset": "mobile",
      "status": "pending" },
    { "id": "memo", "title": "Recommendation", "src": "boards/memo.html", "section": "decision", "preset": "a4" }
  ],
  "notes": [
    { "section": "decision", "text": "Still needs validation with 3 people", "color": "yellow" }
  ],
  "arrows": [
    { "from": "option-a", "to": "memo", "label": "chosen" }
  ]
}
```
- **`lang`:** language of the engine's interface (buttons, help, labels). Set it from the person's saved language
  (`memory/local/preferences.md`, or the project default in `memory/shared/project.md`). Built in: `en`, `es`.
  Without it, the engine uses `<html lang>` and then the browser language. Write the titles, notes and boards in
  that same language: the canvas is for people.
- **Automatic layout:** a board or note without `x`/`y` is placed inside its section, in rows from left to right.
  Set `x`/`y` (board pixels) only when you need an exact position.
- **Sizes (`preset`):** `mobile` 390×844 · `tablet` 834×1194 · `laptop` 1280×800 · `desktop` 1440×900 ·
  `a4` 794×1123 · `square` 1080×1080 · `story` 1080×1920. For any other size, use `w` and `h`.
- **`status: "pending"`:** a planned board that doesn't exist yet (shown dashed; needs no `src`).
- **`entry`:** the board framed on open. `links`: header links to other canvases or pages.
- `note` appears under its board; `notes` are sticky notes (`yellow`, `blue`, `green`, `pink`); `arrows` connect
  boards.
- Every board has its own link: `index.html#<id>`.

## Steps
1. Create the folder with today's date and a lowercase, hyphenated name.
2. Write each board in `boards/<id>.html`: **self-contained** HTML (styles and scripts inline; libraries and fonts
   only from a CDN with a pinned version), designed for the exact size of its board.
3. Write `canvas.json` (with `lang`) and `index.html` as above.
4. Add a line to `artifacts/INDEX.md`: `- YYYY-MM-DD · [Title](path/index.html) — what it is about`.
5. Show it: start `python3 -m http.server 8090` from the repo root (in the background) and share
   `http://localhost:8090/artifacts/YYYY-MM/YYYY-MM-DD-name.canvas/`. Opened as a plain file (no server) it cannot
   load `canvas.json`.
6. If you can, check it with a screenshot (`python3 .agate/agate.py export png …`) before showing it.

## High-resolution screens
When people ask for "real" or "high-res" interfaces, each board is a finished screen, not a sketch: the real size of
its `preset`, careful typography, believable and dense data (no lorem ipsum), icons, states (empty, loading, error)
and, when it applies, light and dark variants. If the project has a design system (for example in
`documents/design-system/`), use it. For visual judgment, install Anthropic's `frontend-design` skill from the skills
library if the project doesn't have it yet.

## Changes and versions
- If nobody has seen the canvas yet, edit it directly.
- If someone already saw it, **don't overwrite it**: copy the folder as `…-v2.canvas/`, change the copy and add the
  new line to the index. That keeps the evolution visible.
- To add a board: create its HTML in `boards/` and add it to `boards` in `canvas.json`.
