# Exa

Search engine built for AI agents. It is openclaude's default engine and the one OpenCode uses for its web search,
so it is the first one to try when an external engine is needed.

## When to prefer it
- Searches by meaning ("companies that do X", "studies about Y") rather than by exact words.
- When speed and precision matter: in published comparisons it beats Tavily (note: those tests were run by vendors).
- To read full, clean pages (`extract`).

## How to use it (the agent does it)
```bash
python3 .agents/skills/web-research/search.py search --engine exa --query "..." --max 10
python3 .agents/skills/web-research/search.py search --engine exa --query "..." --domains a.com,b.com --since 2026-01-01
python3 .agents/skills/web-research/search.py extract --engine exa https://...
```
- `--depth basic`: returns highlighted snippets (cheapest).
- `--depth advanced`: returns up to 2,000 characters of text per result.
- `--depth deep`: Exa's deep search; **it costs more: ask first**.

## API
- Search: `POST https://api.exa.ai/search`, header `x-api-key`. Body: `query`, `numResults`, `type`
  (`auto`, `deep`…), `contents` (`highlights` or `text.maxCharacters`), `includeDomains`, `startPublishedDate`.
- Contents: `POST https://api.exa.ai/contents` with `urls` and `text`.
- The response includes `costDollars`: the script shows it as `cost` so spending can be reported.

## Costs and key
- Key: <https://exa.ai> → dashboard → API keys. Stored in `.env` as `EXA_API_KEY`.
- There is a free keyless tier with usage limits (openclaude uses it by default); with a key, limits are higher.
- Check current prices on the official site before planning any spending.

## Sources
- [openclaude `.env.example` (search providers)](https://github.com/Twigpine/openclaude/blob/main/.env.example)
- [How does opencode implement web search?](https://forums.basehub.com/anomalyco/opencode/34)
- [Exa vs Tavily (Exa)](https://exa.ai/versus/tavily)
- [Tavily vs Exa (cloro)](https://cloro.dev/blog/tavily-vs-exa/)
