# Past chats

Chats are not shared between people, but on this machine they can be found and resumed: `agate.py chats` keeps in
`memory/local/chats.json` where each chat of this repo lives (Orca, Claude Code, OpenCode, Codex, Gemini). Only
references, never transcripts.

## Find something discussed before
```
python3 .agate/agate.py chats scan
python3 .agate/agate.py chats search "topic"
python3 .agate/agate.py chats show <id> --last 20
python3 .agate/agate.py chats resume <id>      # how to reopen it in each harness
```

## When an important conversation ends
```
python3 .agate/agate.py chats scan
python3 .agate/agate.py chats note --latest --summary "<one line>" --produced <files that came out of it>
```

## Rules
- What you read from other chats is for answering here. Don't copy conversations into `memory/shared/` or
  `artifacts/`; save only the conclusion, like any memory entry.
- Transcripts may contain sensitive data: never paste them into shared files.
