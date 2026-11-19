---
name: web-research
description: Methodical web research. Use it for deep research, when the search must be widened with external engines (Exa, Tavily), when the current harness or model has no built-in search, or when the person asks for a specific engine.
---

# web-research

Research the web choosing the engine based on what the current model can do, how deep the topic is, what the person
asks for and which keys are available. The agent runs the commands: the person runs nothing.

## 1. Decide the depth
- **Quick:** one fact, a definition, something specific. The harness's built-in search is enough, if it has one.
- **Deep:** market, competitors, trends, a topic with several parts. Built-in search + an external engine to widen
  and cross-check.
- If the person asked for a specific engine ("search it with Exa"), use that one.

## 2. Check what this model can do
Capability depends on **the harness and the model together** (the same model may search in one harness and not in
another).
- Read `memory/local/capabilities.json` and look for the key `"<harness>/<model>"` (for example
  `"claude-code/claude-opus-5-5"`). If you are not sure of your harness or model, use what you know and record it
  that way.
- Format:
  ```json
  {"claude-code/claude-opus-5-5": {"native_search": true, "checked": "2026-11-19", "note": "verified with verify"}}
  ```
- **Test again** if there is no record, if it is older than 30 days, or if built-in search just failed.

## 3. The test must verify, not trust
A model without search can **make up** that it searched. To test:
1. With your built-in search, look for something recent and checkable (news from this week) and keep one link and
   one sentence that the page says.
2. Verify it:
   ```bash
   python3 .agents/skills/web-research/search.py verify "<url>" --expect "<sentence from the page>"
   ```
3. Only if it returns `"ok": true` and `"found": true`, save `"native_search": true`. If you have no search tool or
   the verification fails, save `false`. Create `memory/local/` if it doesn't exist (it is not committed).

## 4. Check the external keys
```bash
python3 .agents/skills/web-research/search.py keys
```
Returns `{"exa": true|false, "tavily": true|false}`. It never shows the values. Never open or print `.env`.

## 5. Choose the engine
| Situation | What to use |
|---|---|
| The person asked for an engine | That engine (if the key is missing, see below) |
| Quick, built-in search available | Built-in search |
| Quick, no built-in search | The external engine with a key (Exa first) |
| Deep, keys available | Built-in search and **offer to widen** with the external one: "Should I widen this with Exa to cross-check?" |
| Deep, no built-in search | External engine; with two keys, use both to cross-check |
| No built-in search and no keys | Say so clearly and offer to set up a key |

**If a key is needed and missing** (only once the person opts into that engine): register it,
`python3 .agate/agate.py env add EXA_API_KEY --where "exa.ai → Dashboard → API keys" --for web-research` (or
`TAVILY_API_KEY --where "tavily.com → API keys"`), explain in plain words what it is (both have a free plan) and let
the person set it with `python3 .agate/agate.py env set EXA_API_KEY` or in `.env` with the editor. Never in the chat.
`agate.py env check EXA_API_KEY --live` confirms it works without showing it.

Commands:
```bash
python3 .agents/skills/web-research/search.py search --engine exa --query "..." [--depth basic|advanced] [--max 10] [--domains a.com,b.com] [--since 2026-01-01]
python3 .agents/skills/web-research/search.py extract --engine exa <url> [<url> ...] [--max-chars 8000]
```
Details for each engine: `references/exa.md` and `references/tavily.md`.

## 6. Watch the spending
- Normal searches (basic or advanced, a few of them): go ahead without asking.
- **Ask first** before anything expensive: Tavily's research endpoint (4 to 250 credits per query), Exa `deep`
  searches, or batches of more than ~20 searches.
- When done, report in one line how many searches you ran with each engine and the cost or credits if the API
  returned them (`usage` / `cost` in the output).

## 7. Confidentiality
Whatever you search with an external engine goes to a third party. **Never** put internal names, plans, roadmap,
internal figures or user data in the query. Search the topic, not the secret: "retention in board game apps", not
"<our app>'s Q3 retention".

## 8. Read, cross-check and cite
- Don't stop at titles or snippets: open the important sources (`extract` or your reading tool).
- Cross-check: an important fact needs more than one source. Flag what comes from a single source or from a vendor.
- Cite with links. Separate what is confirmed from your own interpretation.
- Write the answer and the report in the person's language.
- If the result is useful later, save it: the report in `artifacts/` and what was decided or learned in `memory/`.
