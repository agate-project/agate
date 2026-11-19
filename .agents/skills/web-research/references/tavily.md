# Tavily

Search engine for AI agents, widely used in interfaces that have no built-in search. It is the alternative to Exa and
useful to cross-check results in deep research.

## When to prefer it
- When there is no Exa key, or to cross-check with a second engine.
- Current-events searches (date filter) and page extraction.

## How to use it (the agent does it)
```bash
python3 .agents/skills/web-research/search.py search --engine tavily --query "..." --max 10
python3 .agents/skills/web-research/search.py search --engine tavily --query "..." --depth advanced --since 2026-01-01
python3 .agents/skills/web-research/search.py extract --engine tavily https://...
```
- `--depth basic`: 1 credit per search. `--depth advanced` (or `deep`): 2 credits.
- Tavily's **research** endpoint (runs the whole research by itself) costs 4 to 250 credits per query: the script
  doesn't use it; if it is ever needed, **ask first**.

## API
- Search: `POST https://api.tavily.com/search`, header `Authorization: Bearer <key>`. Body: `query`,
  `search_depth` (`basic`/`advanced`), `max_results`, `include_domains`, `start_date`, `include_usage`.
- Extract: `POST https://api.tavily.com/extract` with `urls` (1–2 credits per 5 pages).
- With `include_usage` the response includes `usage` (credits used): the script shows it so spending can be reported.

## Costs and key
Figures from third-party sources (November 2026), **confirm on the official site** before planning any spending:

| Plan | Price | Credits |
|---|---|---|
| Free | $0, no card | 1,000 per month |
| Project | ~$30 per month | 4,000 |
| Pay as you go | ~$0.008 per credit | — |

- Key: <https://tavily.com> → dashboard → API keys. Stored in `.env` as `TAVILY_API_KEY`.

## Sources
- [Tavily Pricing 2026](https://vibecodehq.pages.dev/pricing/tavily-pricing)
- [All Tavily plans](https://www.costbench.com/software/web-scraping/tavily/)
- [Tavily vs Exa (You.com)](https://you.com/resources/tavily-vs-exa)
- [Web search APIs for AI agents 2026](https://guptadeepak.com/research/web-search-apis-ai-agents-2026/)
