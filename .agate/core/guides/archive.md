# Archiving and recovering

For anything no longer used (artifacts, documents, memory) or when the repo gets too heavy.

## Archive
1. Note the last commit where it exists: `git log -1 --format=%h -- <path>`.
2. Move it into `archive/` keeping its path: `artifacts/2026-11/x.html` → `archive/artifacts/2026-11/x.html`.
   The contents of `archive/` are not committed: for git it is deleted, but it stays in the history.
3. Add a row to `archive/INDEX.md` (committed): original path, date, commit, reason.
4. If it was listed in an index (`memory/INDEX.md`, `documents/INDEX.md`, `artifacts/INDEX.md`), remove that line.
5. Commit with a clear message.

## Recover
`git checkout <commit> -- <original path>` (the commit is in `archive/INDEX.md`), then add it back to its index.

## Repo size
Archiving does not shrink the git history. To avoid downloading archived content, clone with
`git clone --filter=blob:none <url>`: full history, but file contents only for current files (archived content is
downloaded only if it is ever recovered).
